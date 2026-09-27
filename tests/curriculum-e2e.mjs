import fs from 'node:fs';
import assert from 'node:assert/strict';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const runtimeModules = process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES;
const playwrightModule = runtimeModules
  ? await import(pathToFileURL(path.join(runtimeModules, 'playwright/index.js')).href)
  : await import('playwright');
const { chromium } = playwrightModule.default || playwrightModule;

const baseURL = process.env.CHINESE_STUDY_TEST_URL || 'http://127.0.0.1:18910/';
const data = JSON.parse(fs.readFileSync(new URL('../curriculum/curriculum-v1.json', import.meta.url), 'utf8'));
const firstHsk3 = data.levels.find(x => x.hsk_level === 3).units[0].lessons[0];
const firstWord = firstHsk3.vocabulary[0];
const browser = await chromium.launch({ headless: true });

async function finishVisibleStep(page) {
  const summary = page.locator('.course-summary');
  if (await summary.count()) return false;
  const next = page.locator('#courseNext');
  if (await next.count()) { await next.click(); return true; }
  const input = page.locator('#courseInput');
  const check = page.locator('#courseCheck');
  if (await input.count() && await check.count()) { await input.fill('错'); await check.click(); return true; }
  const tokens = page.locator('[data-token]:not([disabled])');
  if (await tokens.count()) {
    while (await page.locator('[data-token]:not([disabled])').count()) await page.locator('[data-token]:not([disabled])').first().click();
    await check.click(); return true;
  }
  const options = page.locator('.course-option:not([disabled])');
  if (await options.count()) {
    await options.first().click();
    assert.equal(await page.locator('.course-option.correct').count(), 1, 'every choice screen must contain exactly one selectable correct answer');
    return true;
  }
  const self = page.locator('[data-self]:not([disabled])');
  if (await self.count()) { await self.first().click(); return true; }
  const reveal = page.locator('#courseReveal');
  if (await reveal.count() && await reveal.isEnabled()) { await input.fill('我学习中文。'); await reveal.click(); return true; }
  throw new Error('Unknown lesson step: ' + (await page.locator('#courseContent').innerText()));
}

try {
  const context = await browser.newContext();
  const page = await context.newPage();
  await page.addInitScript(() => {
    Object.defineProperty(window, '__spoken', { value: [], writable: true });
    class MockUtterance { constructor(text) { this.text = text; } }
    Object.defineProperty(window, 'SpeechSynthesisUtterance', { value: MockUtterance, configurable: true });
    Object.defineProperty(window, 'speechSynthesis', {
      configurable: true,
      value: {
        paused: false, cancel() {}, resume() {},
        getVoices() { return [{ lang: 'zh-CN', name: 'Test Chinese' }]; },
        speak(utterance) { window.__spoken.push(utterance.text); queueMicrotask(() => utterance.onstart?.()); },
      },
    });
  });
  await page.goto(baseURL);
  await page.locator('#courseOnboarding').waitFor();
  await page.locator('#courseOnboarding [data-level="3"]').click();
  await page.getByText('Продолжить обучение · HSK 3').waitFor();
  const homeStyles = await page.locator('.course-home').evaluate(home => {
    const badge = getComputedStyle(home.querySelector('.course-meta span'));
    const ghost = getComputedStyle(home.querySelector('.ghost'));
    return {
      badgeColor: badge.color,
      badgeBackground: badge.backgroundColor,
      ghostColor: ghost.color,
      ghostRadius: ghost.borderRadius,
    };
  });
  assert.equal(homeStyles.badgeColor, 'rgb(37, 53, 47)');
  assert.equal(homeStyles.badgeBackground, 'rgb(247, 243, 235)');
  assert.equal(homeStyles.ghostColor, 'rgb(37, 53, 47)');
  assert.equal(homeStyles.ghostRadius, '12px');
  assert.equal(await page.locator('#aimFile').getAttribute('multiple'), '');
  assert.equal(await page.locator('#aimCamera').getAttribute('capture'), 'environment');
  assert.match(await page.locator('#view-today .mission').innerText(), /8 новых слов|7 новых слов|9 новых слов/);
  await page.locator('#continueCourse').click();
  await page.getByRole('heading', { name: 'Новая лексика', exact: true }).waitFor();
  await page.locator('#courseNext').click();

  // Deliberately choose a wrong answer and verify that the correct option was
  // not lost when the randomized list was limited to four choices.
  assert.equal(await page.locator('.course-option').filter({ hasText: firstWord.hanzi }).count(), 1);
  const wrong = page.locator('.course-option').filter({ hasNotText: firstWord.hanzi }).first();
  await wrong.click();
  const feedback = page.locator('#courseFeedback');
  assert.match(await feedback.innerText(), /Ошибка/);
  assert.ok((await feedback.innerText()).includes(firstWord.pinyin), 'wrong-answer feedback must include pinyin');
  assert.equal(await page.locator('.course-option.correct').count(), 1);
  assert.equal(await page.locator('#courseNext').count(), 1, 'wrong answer must allow continuing');

  let sawCheckedProduction = false, sawContextListening = false;
  for (let i = 0; i < 100 && !(await page.locator('.course-summary').count()); i++) {
    if (await page.getByRole('heading', { name: 'Восстановите фразу по пиньиню', exact: true }).count()) sawCheckedProduction = true;
    if (await page.getByRole('heading', { name: 'Какое из предложенных слов прозвучало?', exact: true }).count()) {
      sawContextListening = true;
      await page.locator('#courseAudio').click();
      await page.waitForFunction(expected => window.__spoken.at(-1) === expected, firstHsk3.contexts[0].chinese);
    }
    await finishVisibleStep(page);
  }
  await page.locator('.course-summary').waitFor();
  assert.ok(sawContextListening, 'lesson must include sentence listening with an unambiguous target word');
  assert.ok(sawCheckedProduction, 'lesson must use checked phrase production instead of an ungraded free response');
  assert.match(await page.locator('.course-summary').innerText(), /На повторение поставлены|по расписанию/);
  const stateAfterLesson = await page.evaluate(() => JSON.parse(localStorage.getItem('hsk34TrainerV2')));
  assert.ok(stateAfterLesson.curriculum.completed[firstHsk3.id]);
  assert.notEqual(stateAfterLesson.curriculum.currentByLevel['3'], firstHsk3.id);
  assert.ok(Object.keys(stateAfterLesson.words || {}).some(id => id.startsWith('h3-w')));
  assert.ok(stateAfterLesson.curriculum.grammarSrs[firstHsk3.grammar.id]);
  assert.ok(stateAfterLesson.curriculum.lessonResults[firstHsk3.id].skills.listening);

  // Personal material comparison marks known/upcoming/new and words-only mode
  // selects only genuinely new vocabulary without altering Curriculum.
  await page.evaluate(({ known, upcoming }) => {
    document.querySelector('#aiMatModal input[value="words"]').checked = true;
    document.getElementById('aimPreview').innerHTML = `<div class="aim-title">Тест</div><h3>Слова</h3><div class="aim-word"><input type="checkbox" checked><b>${known}</b><small>py</small><span>known</span></div><div class="aim-word"><input type="checkbox" checked><b>${upcoming}</b><small>py</small><span>upcoming</span></div><div class="aim-word"><input type="checkbox" checked><b>不存在词</b><small>bù cúnzài</small><span>new</span></div>`;
  }, { known: firstHsk3.vocabulary[0].hanzi, upcoming: data.levels.find(x => x.hsk_level === 3).units[0].lessons[1].vocabulary[0].hanzi });
  await page.waitForFunction(() => document.querySelector('#aimPreview .card')?.textContent.includes('В материале 3 слов'));
  assert.match(await page.locator('#aimPreview .card').textContent(), /1 уже изучались/);
  assert.equal(await page.locator('#aimPreview .aim-word input:checked').count(), 1);
  await page.locator('#courseFinish').click();

  // Course map and changing level remain available without erasing progress.
  await page.locator('#openCourseRoad').click();
  await page.locator('#view-course.active').waitFor();
  assert.ok(await page.locator('.course-node.done').count() >= 1);
  await page.locator('#courseSettings').click();
  await page.locator('#courseOnboarding [data-level="1"]').click();
  await page.waitForFunction(() => document.body.textContent.includes('Продолжить обучение · HSK 1'));
  const switched = await page.evaluate(() => JSON.parse(localStorage.getItem('hsk34TrainerV2')));
  assert.equal(switched.curriculum.startLevel, 1);
  assert.ok(switched.curriculum.completed[firstHsk3.id], 'changing HSK must keep progress');
  await page.reload();
  await page.waitForFunction(() => document.body.textContent.includes('Продолжить обучение · HSK 1'));
  assert.equal(await page.locator('#courseOnboarding').count(), 0);
  await context.close();

  // Existing users are migrated in place; custom data and history survive.
  const legacyContext = await browser.newContext();
  await legacyContext.addInitScript(() => {
    localStorage.setItem('hsk34TrainerV2', JSON.stringify({
      customWords: [{ id: 'legacy-w', h: '测试', p: 'cèshì', r: 'тест' }],
      customTopics: [{ id: 'legacy-t', title: 'Старая тема', wordIds: ['legacy-w'] }],
      materials: [{ id: 'legacy-m', title: 'Старый материал', wordIds: ['legacy-w'], ts: 1 }],
      history: [{ ts: 1, id: 'legacy-w', ok: true }], words: { 'legacy-w': { seen: 1, due: 0 } },
    }));
  });
  const legacyPage = await legacyContext.newPage();
  await legacyPage.goto(baseURL);
  await legacyPage.locator('#courseOnboarding').waitFor();
  const legacyBefore = await legacyPage.evaluate(() => JSON.parse(localStorage.getItem('hsk34TrainerV2')));
  assert.equal(legacyBefore.customWords[0].id, 'legacy-w');
  assert.equal(legacyBefore.customTopics[0].id, 'legacy-t');
  assert.equal(legacyBefore.materials[0].id, 'legacy-m');
  assert.equal(legacyBefore.history[0].id, 'legacy-w');
  await legacyPage.locator('#courseOnboarding [data-level="4"]').click();
  const legacyAfter = await legacyPage.evaluate(() => JSON.parse(localStorage.getItem('hsk34TrainerV2')));
  assert.equal(legacyAfter.curriculum.startLevel, 4);
  assert.equal(legacyAfter.customWords[0].id, 'legacy-w');
  await legacyContext.close();
  console.log('curriculum-e2e: ok');
} finally {
  await browser.close();
}
