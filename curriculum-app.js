(() => {
  'use strict';
  const CLIENT_VERSION = (() => {
    try {
      const current = document.currentScript?.src
        || [...document.scripts].map(script => script.src).find(src => /(?:^|\/)curriculum-app\.js(?:\?|$)/.test(src));
      if (!current) return 'dev';
      return new URL(current, location.href).searchParams.get('v') || 'dev';
    } catch (_) {
      return 'dev';
    }
  })();
  const CURRICULUM_URL = 'curriculum/curriculum-v1.json?v=1.2.0';
  const DAY = 86400000;
  let curriculum = null;
  let levels = [];
  let lessons = [];
  let lessonById = new Map();
  let wordById = new Map();
  let grammarById = new Map();
  let active = null;
  let activeSteps = [];
  let activePos = 0;
  let activeStats = { correct: 0, total: 0, skills: {}, wordAttempts: {}, grammarAttempts: {}, retryKeys: new Set() };

  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const norm = value => String(value ?? '').replace(/[\s，。！？、,.!?“”"'’]/g, '').toLowerCase();
  const shuffled = items => [...items].sort(() => Math.random() - .5);
  const unique = items => [...new Set(items.filter(Boolean))];
  const nowMs = () => Date.now();

  function ensureCourseState() {
    if (!state.curriculum || typeof state.curriculum !== 'object') {
      state.curriculum = { schemaVersion: 1, startLevel: null, currentByLevel: {}, completed: {}, grammarSrs: {}, lessonResults: {}, updatedAt: 0 };
    }
    const course = state.curriculum;
    course.schemaVersion = 1;
    if (!course.completed || typeof course.completed !== 'object') course.completed = {};
    if (!course.currentByLevel || typeof course.currentByLevel !== 'object') course.currentByLevel = {};
    if (!course.grammarSrs || typeof course.grammarSrs !== 'object') course.grammarSrs = {};
    if (!course.lessonResults || typeof course.lessonResults !== 'object') course.lessonResults = {};
    return course;
  }

  function persistCourse() {
    ensureCourseState().updatedAt = nowMs();
    try { save(); } catch (_) {
      try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (_) {}
    }
  }

  function indexCurriculum(data) {
    curriculum = data;
    levels = data.levels || [];
    lessons = levels.flatMap(level => (level.units || []).flatMap(unit => unit.lessons || []));
    lessonById = new Map(lessons.map(lesson => [lesson.id, lesson]));
    wordById = new Map();
    grammarById = new Map();
    for (const lesson of lessons) {
      for (const word of lesson.vocabulary || []) wordById.set(word.id, word);
      if (lesson.grammar) grammarById.set(lesson.grammar.id, lesson.grammar);
    }
    window.CHINESE_CURRICULUM = data;
    window.CHINESE_CURRICULUM_WORDS = wordById;
  }

  function hydrateRuntimeWords() {
    if (typeof WORDS === 'undefined' || !Array.isArray(WORDS)) return;
    const ids = new Set(WORDS.map(word => String(word.id)));
    for (const lesson of lessons) {
      for (const word of lesson.vocabulary || []) {
        if (ids.has(String(word.id))) continue;
        const example = word.example || {};
        WORDS.push({ id: word.id, h: word.hanzi, p: word.pinyin, r: word.translation_ru, l: lesson.hsk_level, t: 'curriculum', e: `${example.cn || ''}|${example.pinyin || ''}|${example.ru || ''}` });
        ids.add(String(word.id));
      }
    }
  }

  function levelLessons(level) { return lessons.filter(lesson => lesson.hsk_level === Number(level)); }
  function isComplete(id) { return Boolean(ensureCourseState().completed[id]); }
  function currentLesson(level = ensureCourseState().startLevel) {
    const list = levelLessons(level), course = ensureCourseState();
    const explicit = lessonById.get(course.currentByLevel?.[String(level)]);
    if (explicit && explicit.hsk_level === Number(level) && !isComplete(explicit.id)) return explicit;
    const next = list.find(lesson => !isComplete(lesson.id)) || list[list.length - 1] || null;
    if (next) course.currentByLevel[String(level)] = next.id;
    return next;
  }
  function previousComplete(lesson) {
    const list = levelLessons(lesson.hsk_level);
    const index = list.findIndex(x => x.id === lesson.id);
    return index <= 0 || isComplete(list[index - 1].id);
  }
  function dueGrammar() {
    const course = ensureCourseState();
    return Object.entries(course.grammarSrs)
      .filter(([id, item]) => grammarById.has(id) && Number(item.due || 0) <= nowMs())
      .map(([id]) => grammarById.get(id));
  }
  function dueVocabulary() {
    if (typeof dueWords !== 'function') return [];
    return dueWords().filter(word => wordById.has(String(word.id)));
  }
  function reviewCount() { return dueVocabulary().length + dueGrammar().length; }

  function injectStyles() {
    const style = document.createElement('style');
    style.textContent = `
      .course-home{display:grid;grid-template-columns:1fr auto;gap:20px;align-items:center}.course-home h2{margin:6px 0 8px}.course-kicker{color:var(--accent,#98622f);font-weight:850}.course-actions{display:flex;gap:9px;flex-wrap:wrap;margin-top:16px}.course-home .ghost{border:1px solid #d9ccb8!important;border-radius:12px!important;background:#f7f3eb!important;color:#25352f!important;font-weight:850;padding:12px 16px;cursor:pointer}.course-home .ghost:hover{background:#fff!important}.course-review{min-width:190px;text-align:center;border-left:1px solid rgba(255,255,255,.28);padding-left:20px}.course-review b{display:block;font:700 34px Georgia,serif;color:#f7f3eb}.course-review small{display:block;color:#d5ddd8!important;margin:4px 0 11px}.course-meta{display:flex;gap:8px;flex-wrap:wrap}.course-meta span{padding:5px 9px;border-radius:999px;background:var(--paper2,#f5f2eb);color:var(--ink,#26221d);font-size:12px;font-weight:750}.course-home .course-meta span{background:#f7f3eb!important;border:1px solid #d9ccb8!important;color:#25352f!important}.course-level-tabs{display:flex;gap:8px;flex-wrap:wrap;margin:16px 0}.course-level-tabs button{border:1px solid var(--line,#ddd);background:var(--paper,#fff);padding:9px 14px;border-radius:999px;font-weight:800;cursor:pointer}.course-level-tabs button.active{background:var(--ink,#24312c);color:white;border-color:var(--ink,#24312c)}.course-unit{margin:18px 0}.course-unit h3{margin:0 0 10px}.course-road{display:grid;gap:8px}.course-node{width:100%;display:grid;grid-template-columns:38px 1fr auto;gap:12px;align-items:center;text-align:left;border:1px solid var(--line,#ddd);border-radius:13px;background:var(--paper,#fff);padding:11px 13px;cursor:pointer}.course-node:hover{transform:translateY(-1px)}.course-node .dot{width:34px;height:34px;border-radius:50%;display:grid;place-items:center;background:#ece8df;font-weight:900}.course-node.done .dot{background:#dcece2;color:#28503e}.course-node.current{border:2px solid var(--accent,#a8743d);box-shadow:0 4px 18px #0000000d}.course-node.current .dot{background:var(--accent,#a8743d);color:white}.course-node.review .dot{border-radius:10px}.course-node small{color:var(--muted,#777)}.course-settings{float:right}.course-modal{position:fixed;inset:0;display:none;z-index:11000;background:#0009;padding:3vh 14px;overflow:auto}.course-modal.open{display:flex;align-items:flex-start;justify-content:center}.course-dialog{position:relative;width:min(820px,100%);background:var(--paper,#fff);border-radius:20px;padding:24px;box-shadow:0 28px 80px #0007}.course-close{position:absolute;right:15px;top:12px;border:0;background:transparent;font-size:28px;cursor:pointer}.course-progress{height:7px;background:var(--line,#ddd);border-radius:99px;overflow:hidden;margin:12px 0 20px}.course-progress i{display:block;height:100%;background:var(--accent,#a8743d);transition:width .25s}.course-wordgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:9px}.course-word{padding:11px;border:1px solid var(--line,#ddd);border-radius:11px}.course-word b{font:700 24px Georgia,serif}.course-word span,.course-word small{display:block}.course-word small{color:var(--accent,#98622f);font-weight:750}.course-options{display:grid;gap:8px;margin:16px 0}.course-option{border:1px solid var(--line,#ddd);background:var(--paper2,#faf9f5);padding:13px;border-radius:11px;text-align:left;font-size:18px;cursor:pointer}.course-option.correct{border-color:#47835d;background:#e8f4ec}.course-option.wrong{border-color:#b94a3c;background:#fff0ed}.course-feedback{padding:13px;border-radius:11px;margin-top:14px;font-size:16px;line-height:1.55}.course-feedback.ok{background:#e8f4ec}.course-feedback.bad{background:#fff0ed}.course-pinyin{color:var(--accent,#98622f);font-weight:750}.course-next{margin-top:14px;padding:12px 18px;border:0;border-radius:11px;background:var(--ink,#25322d);color:white;font-weight:850;cursor:pointer}.course-input{width:100%;padding:12px;border:1px solid var(--line,#ddd);border-radius:11px;font-size:20px;margin:12px 0}.course-dialogue{white-space:pre-line;font:23px/1.75 Georgia,serif}.course-context{font:700 28px/1.65 Georgia,serif;padding:15px 0}.course-context .focus{color:var(--accent,#98622f);border-bottom:3px solid currentColor}.course-hint{padding:10px 12px;border-left:3px solid var(--accent,#98622f);background:var(--paper2,#faf9f5);margin:12px 0}.course-skill{display:inline-block;padding:4px 8px;border-radius:999px;background:var(--paper2,#f5f2eb);font-size:12px;font-weight:850;letter-spacing:.03em}.course-self-options{display:grid;gap:8px;margin-top:12px}.course-self-option{border:1px solid var(--line,#ddd);background:var(--paper,#fff);padding:12px;border-radius:10px;text-align:left;font-weight:800;cursor:pointer}.course-onboarding{position:fixed;inset:0;z-index:12000;background:linear-gradient(145deg,#1f2e29,#344b41);display:flex;align-items:center;justify-content:center;padding:20px}.course-onboarding-box{width:min(680px,100%);background:#fff;border-radius:22px;padding:28px}.course-level-choice{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;margin-top:18px}.course-level-choice button{padding:20px;border:1px solid #ddd;border-radius:14px;background:#faf8f3;text-align:left;cursor:pointer}.course-level-choice b{display:block;font-size:22px}.course-level-choice small{color:#6f756f}.course-summary{text-align:center;padding:16px}.course-summary .seal{width:72px;height:72px;border-radius:50%;display:grid;place-items:center;background:#e5eee8;margin:auto;font:700 38px Georgia,serif}.course-answer-actions{display:flex;gap:8px;flex-wrap:wrap}.course-audio{padding:12px 16px;border:0;border-radius:999px;background:#f0e8d8;font-weight:800;cursor:pointer}.course-audio-status{margin:8px 0;color:var(--muted,#777);font-size:13px}.course-audio-status.error{color:#9b332b}@media(max-width:700px){.course-home{grid-template-columns:1fr}.course-review{border:0;border-top:1px solid rgba(255,255,255,.28);padding:15px 0 0}.course-level-choice{grid-template-columns:1fr}.course-dialog{padding:20px 16px}.course-node{grid-template-columns:34px 1fr}.course-node>small{display:none}.course-context{font-size:24px}}
    `;
    document.head.appendChild(style);
  }

  function addCourseView() {
    const nav = document.querySelector('nav');
    if (nav && !document.querySelector('[data-view="course"]')) {
      const button = document.createElement('button');
      button.className = 'navbtn'; button.dataset.view = 'course'; button.innerHTML = '<span>课</span>Программа';
      const words = nav.querySelector('[data-view="words"]');
      nav.insertBefore(button, words || null);
      button.onclick = () => showView('course');
    }
    const main = document.querySelector('main');
    if (main && !document.getElementById('view-course')) {
      const section = document.createElement('section');
      section.className = 'view'; section.id = 'view-course';
      section.innerHTML = '<button class="ghost course-settings" id="courseSettings">Сменить уровень</button><div class="eyebrow">课程路线 · программа</div><h2>Путь от HSK 1 до HSK 4</h2><p>Можно открыть любой уровень и любой предыдущий урок. Текущий путь определяется выбранным уровнем.</p><div class="course-level-tabs" id="courseLevelTabs"></div><div id="courseRoad"></div>';
      main.appendChild(section);
      section.querySelector('#courseSettings').onclick = () => showOnboarding(true);
    }
  }

  function showView(name) {
    document.querySelectorAll('.navbtn').forEach(x => x.classList.toggle('active', x.dataset.view === name));
    document.querySelectorAll('.view').forEach(x => x.classList.toggle('active', x.id === `view-${name}`));
    if (name === 'course') renderCourseRoad();
    const title = document.getElementById('title');
    if (title && name === 'course') title.textContent = '一步一步，学到 HSK 4。';
  }

  function renderCourseHome() {
    const mission = document.querySelector('#view-today .mission');
    const lesson = currentLesson();
    if (!mission || !lesson) return;
    const level = levels.find(x => x.hsk_level === lesson.hsk_level);
    const unit = level?.units?.find(x => x.id === lesson.unit_id);
    const count = lesson.vocabulary?.length || 0;
    mission.innerHTML = `
      <div class="course-home">
        <div><div class="course-kicker">Продолжить обучение · HSK ${lesson.hsk_level}</div>
          <h2>${esc(unit?.title || '')}</h2><h3>${esc(lesson.title)}</h3>
          <div class="course-meta"><span>Урок ${lesson.number} из ${levelLessons(lesson.hsk_level).length}</span><span>${count ? `${count} новых слов` : 'контрольное повторение'}</span><span>${lesson.grammar ? '1 новая конструкция' : 'закрепление грамматики'}</span><span>≈ ${lesson.estimated_minutes} минут</span></div>
          <div class="course-actions"><button class="primary" id="continueCourse">Продолжить</button><button class="ghost" id="openCourseRoad">Вся программа</button></div>
        </div>
        <div class="course-review"><b>${reviewCount()}</b><small>элементов пора повторить</small><button class="ghost" id="courseReview">Повторить</button></div>
      </div>`;
    mission.querySelector('#continueCourse').onclick = () => startLesson(lesson.id);
    mission.querySelector('#openCourseRoad').onclick = () => showView('course');
    mission.querySelector('#courseReview').onclick = startCourseReview;
  }

  function renderCourseRoad(selectedLevel) {
    const course = ensureCourseState();
    const levelNo = Number(selectedLevel || course.startLevel || document.querySelector('#courseLevelTabs .active')?.dataset.level || 1);
    const tabs = document.getElementById('courseLevelTabs');
    const road = document.getElementById('courseRoad');
    if (!tabs || !road) return;
    tabs.innerHTML = levels.map(level => `<button data-level="${level.hsk_level}" class="${level.hsk_level === levelNo ? 'active' : ''}">HSK ${level.hsk_level}</button>`).join('');
    tabs.querySelectorAll('button').forEach(button => button.onclick = () => renderCourseRoad(Number(button.dataset.level)));
    const level = levels.find(x => x.hsk_level === levelNo);
    const current = currentLesson(levelNo);
    road.innerHTML = (level?.units || []).map(unit => `<section class="course-unit"><h3>Раздел ${unit.number}. ${esc(unit.title)}</h3><div class="course-road">${unit.lessons.map(lesson => {
      const done = isComplete(lesson.id), currentFlag = current?.id === lesson.id, available = previousComplete(lesson);
      const stateClass = done ? 'done' : currentFlag ? 'current' : available ? 'available' : 'future';
      return `<button class="course-node ${stateClass} ${lesson.type === 'review' ? 'review' : ''}" data-lesson="${esc(lesson.id)}"><span class="dot">${done ? '✓' : lesson.type === 'review' ? '复' : lesson.number}</span><span><b>${esc(lesson.title)}</b><small>${lesson.vocabulary?.length ? `${lesson.vocabulary.length} слов · ` : ''}${lesson.estimated_minutes} мин</small></span><small>${done ? 'пройдено' : currentFlag ? 'сейчас' : available ? 'доступно' : 'ещё не пройдено'}</small></button>`;
    }).join('')}</div></section>`).join('');
    road.querySelectorAll('[data-lesson]').forEach(button => button.onclick = () => startLesson(button.dataset.lesson));
  }

  function makeModal() {
    if (document.getElementById('courseModal')) return;
    const modal = document.createElement('div');
    modal.id = 'courseModal'; modal.className = 'course-modal';
    modal.innerHTML = '<div class="course-dialog"><button class="course-close" id="courseClose">×</button><div id="coursePhase"></div><div class="course-progress"><i id="courseProgress"></i></div><div id="courseContent"></div></div>';
    document.body.appendChild(modal);
    modal.querySelector('#courseClose').onclick = closeLesson;
    modal.addEventListener('click', event => { if (event.target === modal) closeLesson(); });
    window.addEventListener('popstate', () => { if (modal.classList.contains('open')) closeLesson(false); });
  }

  function startLesson(id) {
    const lesson = lessonById.get(id);
    if (!lesson) return;
    ensureCourseState().currentByLevel[String(lesson.hsk_level)] = lesson.id;
    persistCourse();
    active = lesson;
    activeSteps = lesson.type === 'review' ? buildCheckpointSteps(lesson) : buildLessonSteps(lesson);
    activePos = 0; activeStats = { correct: 0, total: 0, skills: {}, wordAttempts: {}, grammarAttempts: {}, retryKeys: new Set() };
    makeModal();
    document.getElementById('courseModal').classList.add('open');
    try { history.pushState({ courseLesson: id }, ''); } catch (_) {}
    renderStep();
  }

  function closeLesson(goBack = true) {
    document.getElementById('courseModal')?.classList.remove('open');
    active = null; activeSteps = []; activePos = 0;
    if (goBack && history.state?.courseLesson) history.back();
  }

  function answerOptions(answer, distractors, limit = 4) {
    const alternatives = shuffled(unique(distractors).filter(value => value && value !== answer)).slice(0, Math.max(0, limit - 1));
    return shuffled([answer, ...alternatives]);
  }

  function wordOptions(word, field = 'translation_ru', excluded = []) {
    const blocked = new Set(excluded);
    const same = [...wordById.values()]
      .filter(x => x.id !== word.id && (field !== 'translation_ru' || x.hanzi !== word.hanzi) && x[field] && x[field] !== word[field] && !blocked.has(x[field]))
      .map(x => x[field]);
    return answerOptions(word[field], same);
  }

  function lessonWordOptions(word, field = 'translation_ru', excluded = []) {
    const blocked = new Set(excluded);
    const usable = x => x.id !== word.id && (field !== 'translation_ru' || x.hanzi !== word.hanzi) && x[field] && x[field] !== word[field] && !blocked.has(x[field]);
    const local = (active?.vocabulary || []).filter(usable).map(x => x[field]);
    const sameLevel = lessons.filter(x => x.hsk_level === active?.hsk_level).flatMap(x => x.vocabulary || [])
      .filter(usable).map(x => x[field]);
    return answerOptions(word[field], [...shuffled(local), ...shuffled(sameLevel)]);
  }

  function contextWord(context) { return wordById.get(String(context?.focus_word_id)); }
  function contextForWord(word) {
    for (const lesson of lessons) {
      const found = (lesson.contexts || []).find(context => String(context.focus_word_id) === String(word.id));
      if (found) return found;
    }
    return null;
  }

  function buildLessonSteps(lesson) {
    const words = lesson.vocabulary || [];
    const contexts = lesson.contexts || [];
    if (contexts.length >= 3) {
      const [first, second, third] = contexts;
      const contextsByWord = new Map(contexts.map(context => [String(context.focus_word_id), context]));
      const drills = words.map((word, index) => {
        const context = contextsByWord.get(String(word.id));
        if (context === first) return { type: 'context-listening', context, word, skill: 'listening' };
        if (context === second) return { type: 'context-reading', context, word, skill: 'reading' };
        if (context === third) return { type: 'context-cloze', context, word, skill: 'fill_blank' };
        if (index % 3 === 0) return { type: 'listening-word', word, skill: 'listening' };
        if (index % 2 === 0) return { type: 'ru-hanzi', word, skill: 'recognition' };
        return { type: 'hanzi-ru', word, skill: 'recognition' };
      });
      const split = Math.min(4, drills.length);
      return [
        { type: 'intro', words },
        ...drills.slice(0, split),
        { type: 'grammar', grammar: lesson.grammar },
        { type: 'grammar-use', grammar: lesson.grammar, skill: 'grammar' },
        ...drills.slice(split),
        { type: 'context-order', context: third, word: contextWord(third), skill: 'word_order' },
        { type: 'context-production', context: first, word: contextWord(first), skill: 'active_speech' },
      ].filter(step => !Object.values(step).some(value => value === undefined));
    }
    const ex = lesson.exercises || {};
    return [
      { type: 'intro', words },
      ...words.slice(0, 3).map((word, index) => ({ type: index % 2 ? 'ru-hanzi' : 'hanzi-ru', word })),
      { type: 'listening', item: ex.listening?.[0], word: words[0] },
      { type: 'grammar', grammar: lesson.grammar },
      { type: 'examples', examples: lesson.examples || [] },
      { type: 'dialogue', dialogue: lesson.dialogue },
      { type: 'choice', item: ex.comprehension?.[0] },
      { type: 'word-order', item: ex.word_order?.[0] },
      { type: 'fill', item: ex.fill_blank?.[0] },
      { type: 'translation', item: ex.translation_ru_cn?.[0] },
      { type: 'active', item: ex.active_answer?.[0] },
    ].filter(step => !Object.values(step).some(value => value === undefined));
  }

  function buildCheckpointSteps(lesson) {
    const source = (lesson.review_lesson_ids || []).flatMap(id => lessonById.get(id)?.vocabulary || []);
    const words = shuffled(source).slice(0, 8);
    const grammars = shuffled((lesson.review_grammar_ids || []).map(id => grammarById.get(id)).filter(Boolean)).slice(0, 4);
    const contexts = shuffled((lesson.review_lesson_ids || []).flatMap(id => lessonById.get(id)?.contexts || []));
    if (contexts.length >= 3) {
      const [first, second, third] = contexts;
      const word = contextWord(first) || words[0];
      return [
        { type: 'context-listening', context: first, word, skill: 'listening', review: true },
        { type: 'ru-hanzi', word: contextWord(second) || words[1] || word, skill: 'recognition', review: true },
        { type: 'grammar-review', grammar: grammars[0], skill: 'grammar', review: true },
        { type: 'context-reading', context: second, word: contextWord(second), skill: 'reading', review: true },
        { type: 'context-order', context: third, word: contextWord(third), skill: 'word_order', review: true },
        { type: 'context-production', context: first, word, skill: 'active_speech', review: true },
      ].filter(step => !('word' in step) || step.word).filter(step => !('grammar' in step) || step.grammar);
    }
    return [
      ...words.map((word, index) => ({ type: index % 3 === 0 ? 'listening-word' : index % 2 ? 'ru-hanzi' : 'hanzi-ru', word, review: true })),
      ...grammars.map(grammar => ({ type: 'grammar-review', grammar })),
    ];
  }

  function renderStep() {
    const phase = document.getElementById('coursePhase');
    const content = document.getElementById('courseContent');
    const progress = document.getElementById('courseProgress');
    if (!active || !phase || !content) return;
    if (activePos >= activeSteps.length) return finishLesson();
    const step = activeSteps[activePos];
    phase.innerHTML = `<div class="eyebrow">HSK ${active.hsk_level} · ${esc(active.title)}</div><b>${activePos + 1} из ${activeSteps.length}</b>`;
    progress.style.width = `${activePos / activeSteps.length * 100}%`;
    const renderers = {
      intro: renderIntro, 'hanzi-ru': renderHanziRu, 'ru-hanzi': renderRuHanzi,
      listening: renderListening, 'listening-word': renderListeningWord, grammar: renderGrammar,
      examples: renderExamples, dialogue: renderDialogue, choice: renderChoice,
      'word-order': renderWordOrder, fill: renderFill, translation: renderTranslation,
      active: renderActive, 'grammar-review': renderGrammarReview,
      'context-listening': renderContextListening, 'context-reading': renderContextReading,
      'context-order': renderContextOrder, 'context-cloze': renderContextCloze,
      'context-translation': renderContextTranslation, 'context-production': renderContextProduction,
      'grammar-use': renderGrammarUse,
    };
    (renderers[step.type] || renderUnsupported)(content, step);
  }

  function nextButton(label = 'Дальше') { return `<button class="course-next" id="courseNext">${label}</button>`; }
  function wireNext() { const b = document.getElementById('courseNext'); if (b) b.onclick = () => { activePos++; renderStep(); }; }
  function markResult(ok, skill = 'general', word = null, grammarId = null) {
    activeStats.total++; if (ok) activeStats.correct++;
    const bucket = activeStats.skills[skill] || { correct: 0, total: 0 };
    bucket.total++; if (ok) bucket.correct++; activeStats.skills[skill] = bucket;
    if (word) {
      const item = activeStats.wordAttempts[word.id] || { correct: 0, total: 0 };
      item.total++; if (ok) item.correct++; activeStats.wordAttempts[word.id] = item;
    }
    if (grammarId) {
      const item = activeStats.grammarAttempts[grammarId] || { correct: 0, total: 0 };
      item.total++; if (ok) item.correct++; activeStats.grammarAttempts[grammarId] = item;
    }
  }

  function queueRetry(step) {
    if (step.retry) return;
    const key = `${step.type}:${step.word?.id || step.grammar?.id || step.context?.source_sentence_id || activePos}`;
    if (activeStats.retryKeys.has(key)) return;
    activeStats.retryKeys.add(key);
    activeSteps.splice(Math.min(activeSteps.length, activePos + 3), 0, { ...step, retry: true });
  }

  function recordStepResult(step, ok) {
    markResult(ok, step.skill || step.type, step.word || null, step.grammar?.id || null);
    if (step.review && step.word) gradeRuntimeWord(step.word, ok);
    if (step.review && step.grammar) gradeGrammar(step.grammar.id, ok);
    if (!ok) queueRetry(step);
  }

  function renderIntro(content, step) {
    content.innerHTML = `<h2>Новая лексика</h2><p>Сначала познакомьтесь со словами. Нажмите на китайское слово, чтобы услышать его.</p><div class="course-wordgrid">${step.words.map(word => `<button class="course-word" data-say="${esc(word.hanzi)}"><b>${esc(word.hanzi)}</b><small>${esc(word.pinyin)}</small><span>${esc(word.translation_ru)}</span></button>`).join('')}</div>${nextButton('Начать упражнения')}`;
    content.querySelectorAll('[data-say]').forEach(button => button.onclick = () => speak(button.dataset.say)); wireNext();
  }

  function renderHanziRu(content, step) {
    const options = lessonWordOptions(step.word);
    renderOptions(content, `<div class="course-skill">Узнавание</div><h2>${esc(step.word.hanzi)}</h2><div class="course-pinyin">${esc(step.word.pinyin)}</div>`, options, step.word.translation_ru, step.word, '', step);
  }

  function renderRuHanzi(content, step) {
    const options = lessonWordOptions(step.word, 'hanzi');
    renderOptions(content, `<div class="course-skill">Узнавание</div><h2>${esc(step.word.translation_ru)}</h2><div class="course-pinyin">${esc(step.word.pinyin)}</div><p>Выберите иероглифическую запись этого слова.</p>`, options, step.word.hanzi, step.word, '', step);
  }

  function renderOptions(content, questionHtml, options, answer, word, explanation = '', step = null) {
    const safeOptions = answerOptions(String(answer), options);
    content.innerHTML = `${questionHtml}<div class="course-options">${safeOptions.map(value => `<button class="course-option" data-value="${esc(value)}">${esc(value)}</button>`).join('')}</div><div id="courseFeedback"></div>`;
    content.querySelectorAll('.course-option').forEach(button => button.onclick = () => {
      const ok = button.dataset.value === String(answer); if (step) recordStepResult(step, ok); else markResult(ok);
      content.querySelectorAll('.course-option').forEach(item => { item.disabled = true; if (item.dataset.value === String(answer)) item.classList.add('correct'); });
      if (!ok) button.classList.add('wrong');
      const chosen = [...wordById.values()].find(x => x.hanzi === button.dataset.value);
      document.getElementById('courseFeedback').innerHTML = `<div class="course-feedback ${ok ? 'ok' : 'bad'}"><b>${ok ? 'Верно' : 'Ошибка'}</b>${!ok && chosen ? `<div>Вы выбрали: ${esc(chosen.hanzi)} · <span class="course-pinyin">${esc(chosen.pinyin)}</span></div>` : ''}<div>Правильно: <b>${esc(answer)}</b>${word ? ` · <span class="course-pinyin">${esc(word.pinyin)}</span>` : ''}</div>${explanation ? `<small>${esc(explanation)}</small>` : ''}</div>${nextButton()}`;
      wireNext();
    });
  }

  function renderListening(content, step) {
    const item = step.item;
    content.innerHTML = `<div class="tiny">Аудирование</div><h2>${esc(item.question_ru)}</h2><button class="course-audio" id="courseAudio">▶ Прослушать</button><div class="course-options">${item.options.map(value => `<button class="course-option" data-value="${esc(value)}">${esc(value)}</button>`).join('')}</div><div id="courseFeedback"></div>`;
    document.getElementById('courseAudio').onclick = () => speak(item.audio_text);
    content.querySelectorAll('.course-option').forEach(button => button.onclick = () => {
      const ok = button.dataset.value === item.answer; markResult(ok);
      content.querySelectorAll('.course-option').forEach(x => { x.disabled = true; if (x.dataset.value === item.answer) x.classList.add('correct'); }); if (!ok) button.classList.add('wrong');
      const chosen = [...wordById.values()].find(x => x.hanzi === button.dataset.value);
      document.getElementById('courseFeedback').innerHTML = `<div class="course-feedback ${ok ? 'ok' : 'bad'}"><b>${ok ? 'Верно' : 'Ошибка'}</b>${!ok && chosen ? `<div>Неверное слово: ${esc(chosen.hanzi)} · <span class="course-pinyin">${esc(chosen.pinyin)}</span></div>` : ''}<div>Правильно: ${esc(item.answer)} · <span class="course-pinyin">${esc(step.word?.pinyin || item.pinyin)}</span></div></div>${nextButton()}`; wireNext();
    });
  }

  function renderListeningWord(content, step) {
    const options = wordOptions(step.word, 'hanzi');
    content.innerHTML = `<div class="tiny">Повторение · аудирование</div><h2>Какое слово прозвучало?</h2><button class="course-audio" id="courseAudio">▶ Прослушать</button><div class="course-options">${options.map(x => `<button class="course-option" data-value="${esc(x)}">${esc(x)}</button>`).join('')}</div><div id="courseFeedback"></div>`;
    document.getElementById('courseAudio').onclick = () => speak(step.word.hanzi);
    content.querySelectorAll('.course-option').forEach(button => button.onclick = () => {
      const ok = button.dataset.value === step.word.hanzi; recordStepResult(step, ok); if (step.review) gradeRuntimeWord(step.word, ok);
      content.querySelectorAll('.course-option').forEach(x => { x.disabled = true; if (x.dataset.value === step.word.hanzi) x.classList.add('correct'); }); if (!ok) button.classList.add('wrong');
      const chosen = [...wordById.values()].find(x => x.hanzi === button.dataset.value);
      document.getElementById('courseFeedback').innerHTML = `<div class="course-feedback ${ok ? 'ok' : 'bad'}"><b>${ok ? 'Верно' : 'Ошибка'}</b>${!ok && chosen ? `<div>Вы выбрали: ${esc(chosen.hanzi)} · <span class="course-pinyin">${esc(chosen.pinyin)}</span></div>` : ''}<div>Правильно: ${esc(step.word.hanzi)} · <span class="course-pinyin">${esc(step.word.pinyin)}</span></div></div>${nextButton()}`; wireNext();
    });
  }

  function renderGrammar(content, step) {
    const g = step.grammar;
    content.innerHTML = `<div class="tiny">Новая грамматика</div><h2>${esc(g.title)}</h2><div class="card"><h3>${esc(g.pattern)}</h3><p>${esc(g.explanation_ru)}</p></div>${nextButton('Понятно, к примерам')}`; wireNext();
  }

  function renderExamples(content, step) {
    content.innerHTML = `<div class="tiny">Примеры</div><h2>Посмотрите на слова в предложениях</h2>${step.examples.map(example => `<div class="card" style="margin:9px 0"><div style="font:21px Georgia,serif">${esc(example.cn)}</div><div class="course-pinyin">${esc(example.pinyin)}</div><small>${esc(example.ru)}</small></div>`).join('')}${nextButton()}`; wireNext();
  }

  function renderDialogue(content, step) {
    content.innerHTML = `<div class="tiny">Короткий диалог</div><h2>Прочитайте и прослушайте</h2><button class="course-audio" id="courseAudio">▶ Прослушать</button><div class="course-dialogue">${esc(step.dialogue.cn)}</div><details><summary>Пиньинь и перевод</summary><div class="course-pinyin" style="white-space:pre-line">${esc(step.dialogue.pinyin)}</div><p>${esc(step.dialogue.ru)}</p></details>${nextButton()}`;
    document.getElementById('courseAudio').onclick = () => speak(step.dialogue.cn.replace(/[AB]：/g, '')); wireNext();
  }

  function contextText(context, mode = 'plain') {
    const text = String(context?.chinese || '');
    const focus = String(context?.focus_hanzi || '');
    if (!focus || !text.includes(focus)) return esc(text);
    if (mode === 'blank') {
      const index = text.indexOf(focus);
      return `${esc(text.slice(0, index))}<b class="focus">＿＿</b>${esc(text.slice(index + focus.length))}`;
    }
    if (mode === 'highlight') return text.split(focus).map(esc).join(`<span class="focus">${esc(focus)}</span>`);
    return esc(text);
  }

  function renderContextListening(content, step) {
    const { context, word } = step;
    const otherWordsInSentence = (active?.vocabulary || [])
      .filter(item => item.id !== word.id && context.chinese.includes(item.hanzi))
      .map(item => item.hanzi);
    const options = lessonWordOptions(word, 'hanzi', otherWordsInSentence);
    content.innerHTML = `<div class="course-skill">Аудирование</div><h2>Какое из предложенных слов прозвучало?</h2><p>Сначала слушайте без текста. Фразу можно повторить медленнее.</p><div class="course-answer-actions"><button class="course-audio" id="courseAudio">▶ Обычная скорость</button><button class="course-audio" id="courseAudioSlow">▶ Медленно</button></div><div class="course-options">${options.map(value => `<button class="course-option" data-value="${esc(value)}">${esc(value)}</button>`).join('')}</div><div id="courseFeedback"></div>`;
    document.getElementById('courseAudio').onclick = () => speak(context.chinese, .86);
    document.getElementById('courseAudioSlow').onclick = () => speak(context.chinese, .64);
    content.querySelectorAll('.course-option').forEach(button => button.onclick = () => {
      const ok = button.dataset.value === word.hanzi; recordStepResult(step, ok);
      content.querySelectorAll('.course-option').forEach(item => { item.disabled = true; if (item.dataset.value === word.hanzi) item.classList.add('correct'); });
      if (!ok) button.classList.add('wrong');
      const chosen = [...wordById.values()].find(item => item.hanzi === button.dataset.value);
      document.getElementById('courseFeedback').innerHTML = `<div class="course-feedback ${ok ? 'ok' : 'bad'}"><b>${ok ? 'Услышали верно' : 'Пока не совпало'}</b>${!ok && chosen ? `<div>Ваш выбор: ${esc(chosen.hanzi)} · <span class="course-pinyin">${esc(chosen.pinyin)}</span></div>` : ''}<div class="course-context">${contextText(context, 'highlight')}</div><div class="course-pinyin">${esc(context.pinyin)}</div><div>${esc(word.hanzi)} — ${esc(word.translation_ru)}</div></div>${nextButton()}`;
      wireNext();
    });
  }

  function renderContextReading(content, step) {
    const { context, word } = step;
    const options = lessonWordOptions(word, 'translation_ru');
    renderOptions(content, `<div class="course-skill">Чтение в контексте</div><div class="course-context">${contextText(context, 'highlight')}</div><h2>Выберите словарный перевод «${esc(word.hanzi)}»</h2><p>Пиньинь всей фразы появится после ответа.</p>`, options, word.translation_ru, word, context.pinyin, step);
  }

  function renderGrammarUse(content, step) {
    const grammar = step.grammar;
    const pool = lessons.filter(lesson => lesson.hsk_level === active.hsk_level && lesson.grammar && lesson.grammar.id !== grammar.id).map(lesson => lesson.grammar);
    const options = shuffled(unique([grammar.pattern, ...shuffled(pool).slice(0, 3).map(item => item.pattern)])).slice(0, 4);
    renderOptions(content, `<div class="course-skill">Грамматика · форма</div><h2>Выберите схему конструкции «${esc(grammar.title)}»</h2><div class="course-hint">${esc(grammar.explanation_ru)}</div>`, options, grammar.pattern, null, `${grammar.title}: ${grammar.explanation_ru}`, step);
  }

  function renderContextOrder(content, step) {
    const { context } = step, chosen = [];
    content.innerHTML = `<div class="course-skill">Порядок слов</div><h2>Восстановите естественную фразу</h2><div id="courseBuilt" class="card course-context" style="min-height:62px"></div><div class="course-answer-actions" id="courseTokens">${shuffled(context.tokens).map((token, index) => `<button class="course-option" data-i="${index}" data-token="${esc(token)}">${esc(token)}</button>`).join('')}</div><div class="course-answer-actions"><button class="ghost" id="courseReset">Сбросить</button><button class="course-next" id="courseCheck">Проверить</button></div><div id="courseFeedback"></div>`;
    const draw = () => { document.getElementById('courseBuilt').textContent = chosen.map(item => item.token).join(''); };
    content.querySelectorAll('[data-token]').forEach(button => button.onclick = () => { chosen.push({ token: button.dataset.token, button }); button.disabled = true; draw(); });
    document.getElementById('courseReset').onclick = () => { chosen.splice(0).forEach(item => { item.button.disabled = false; }); draw(); };
    document.getElementById('courseCheck').onclick = () => {
      const ok = norm(chosen.map(item => item.token).join('')) === norm(context.chinese); recordStepResult(step, ok);
      document.getElementById('courseCheck').disabled = true;
      document.getElementById('courseFeedback').innerHTML = `<div class="course-feedback ${ok ? 'ok' : 'bad'}"><b>${ok ? 'Порядок естественный' : 'Порядок нужно поправить'}</b><div class="course-context">${esc(context.chinese)}</div><div class="course-pinyin">${esc(context.pinyin)}</div>${!ok ? '<small>Сначала найдите подлежащее и время/место, затем сказуемое и объект.</small>' : ''}</div>${nextButton()}`;
      wireNext();
    };
  }

  function renderContextCloze(content, step) {
    const { context, word } = step;
    content.innerHTML = `<div class="course-skill">Пропуск в контексте</div><h2>Восстановите слово</h2><div class="course-context">${contextText(context, 'blank')}</div><div class="course-hint">Нужный смысл: ${esc(word.translation_ru)}</div><input class="course-input" id="courseInput" lang="zh" autocomplete="off" placeholder="Введите иероглифы"><button class="course-next" id="courseCheck">Проверить</button><div id="courseFeedback"></div>`;
    document.getElementById('courseCheck').onclick = () => {
      const value = document.getElementById('courseInput').value, ok = norm(value) === norm(word.hanzi); recordStepResult(step, ok);
      const chosen = [...wordById.values()].find(item => value.includes(item.hanzi));
      document.getElementById('courseCheck').disabled = true;
      document.getElementById('courseFeedback').innerHTML = `<div class="course-feedback ${ok ? 'ok' : 'bad'}"><b>${ok ? 'Верно' : 'Нужно исправить'}</b>${!ok && chosen ? `<div>Введено: ${esc(chosen.hanzi)} · <span class="course-pinyin">${esc(chosen.pinyin)}</span></div>` : ''}<div class="course-context">${contextText(context, 'highlight')}</div><div class="course-pinyin">${esc(context.pinyin)}</div><div>${esc(word.hanzi)} — ${esc(word.translation_ru)}</div></div>${nextButton()}`;
      wireNext();
    };
  }

  function renderContextTranslation(content, step) {
    const { context, word } = step;
    content.innerHTML = `<div class="course-skill">Русский → 中文</div><h2>Напишите по-китайски</h2><div class="course-hint">${esc(word.translation_ru)}</div><input class="course-input" id="courseInput" lang="zh" autocomplete="off" placeholder="Введите слово"><button class="course-next" id="courseCheck">Проверить</button><div id="courseFeedback"></div>`;
    document.getElementById('courseCheck').onclick = () => {
      const value = document.getElementById('courseInput').value, ok = norm(value) === norm(word.hanzi); recordStepResult(step, ok);
      const chosen = [...wordById.values()].find(item => value.includes(item.hanzi));
      document.getElementById('courseCheck').disabled = true;
      document.getElementById('courseFeedback').innerHTML = `<div class="course-feedback ${ok ? 'ok' : 'bad'}"><b>${ok ? 'Верно' : 'Нужно исправить'}</b>${!ok && chosen ? `<div>Введено: ${esc(chosen.hanzi)} · <span class="course-pinyin">${esc(chosen.pinyin)}</span></div>` : ''}<div>Правильно: <b>${esc(word.hanzi)}</b> · <span class="course-pinyin">${esc(word.pinyin)}</span></div><div class="course-hint">Живой контекст: ${esc(context.chinese)}<br><span class="course-pinyin">${esc(context.pinyin)}</span></div></div>${nextButton()}`;
      wireNext();
    };
  }

  function renderContextProduction(content, step) {
    const { context, word } = step;
    content.innerHTML = `<div class="course-skill">Воспроизведение</div><h2>Восстановите фразу по пиньиню</h2><div class="course-pinyin" style="font-size:20px;line-height:1.6">${esc(context.pinyin)}</div><div class="course-hint">Ключевое слово: ${esc(word.translation_ru)} → ${esc(word.hanzi)}</div><p>Напишите всю фразу иероглифами. Знаки препинания можно не ставить.</p><button class="course-audio" id="courseAudio">▶ Прослушать</button><textarea class="course-input" id="courseInput" rows="3" lang="zh" autocomplete="off" placeholder="Восстановите китайскую фразу"></textarea><button class="course-next" id="courseCheck">Проверить</button><div id="courseFeedback"></div>`;
    document.getElementById('courseAudio').onclick = () => speak(context.chinese, .78);
    document.getElementById('courseCheck').onclick = () => {
      const value = document.getElementById('courseInput').value.trim();
      const ok = norm(value) === norm(context.chinese); recordStepResult(step, ok);
      document.getElementById('courseCheck').disabled = true;
      document.getElementById('courseFeedback').innerHTML = `<div class="course-feedback ${ok ? 'ok' : 'bad'}"><b>${ok ? 'Фраза восстановлена' : 'Сверьте ответ с исходной фразой'}</b>${!ok && value ? `<div>Ваш ответ: ${esc(value)}</div>` : ''}<div class="course-context">${contextText(context, 'highlight')}</div><div class="course-pinyin">${esc(context.pinyin)}</div>${!ok ? '<small>Проверьте служебные слова и порядок частей предложения. Это задание вернётся ещё раз.</small>' : ''}</div>${nextButton()}`;
      wireNext();
    };
  }

  function renderChoice(content, step) {
    const item = step.item;
    renderOptions(content, `<div class="tiny">Понимание</div><div class="course-dialogue">${esc(item.text_cn)}</div><div class="course-pinyin">${esc(item.text_pinyin)}</div><h3>${esc(item.question_ru)}</h3>`, shuffled(item.options), item.answer, null);
  }

  function renderWordOrder(content, step) {
    const item = step.item, chosen = [];
    content.innerHTML = `<div class="tiny">Порядок слов</div><h2>Соберите предложение</h2><div id="courseBuilt" class="card" style="min-height:54px"></div><div class="course-answer-actions" id="courseTokens">${shuffled(item.tokens).map((token, i) => `<button class="course-option" data-i="${i}" data-token="${esc(token)}">${esc(token)}</button>`).join('')}</div><button class="course-next" id="courseCheck">Проверить</button><div id="courseFeedback"></div>`;
    content.querySelectorAll('[data-token]').forEach(button => button.onclick = () => { chosen.push(button.dataset.token); button.disabled = true; document.getElementById('courseBuilt').textContent = chosen.join(''); });
    document.getElementById('courseCheck').onclick = () => {
      const ok = norm(chosen.join('')) === norm(item.answer); markResult(ok);
      document.getElementById('courseFeedback').innerHTML = `<div class="course-feedback ${ok ? 'ok' : 'bad'}"><b>${ok ? 'Верно' : 'Ошибка в порядке слов'}</b><div>Правильно: ${esc(item.answer)}</div><div class="course-pinyin">${esc(item.pinyin)}</div></div>${nextButton()}`; wireNext();
    };
  }

  function renderFill(content, step) {
    const item = step.item;
    content.innerHTML = `<div class="tiny">Заполните пропуск</div><h2>${esc(item.sentence)}</h2><input class="course-input" id="courseInput" lang="zh" placeholder="Введите слово"><button class="course-next" id="courseCheck">Проверить</button><div id="courseFeedback"></div>`;
    document.getElementById('courseCheck').onclick = () => checkText(item.answer, item.pinyin, 'courseInput');
  }

  function renderTranslation(content, step) {
    const item = step.item;
    content.innerHTML = `<div class="tiny">Русский → 中文</div><h2>${esc(item.prompt_ru)}</h2><input class="course-input" id="courseInput" lang="zh" placeholder="Напишите по-китайски"><button class="course-next" id="courseCheck">Проверить</button><div id="courseFeedback"></div>`;
    document.getElementById('courseCheck').onclick = () => checkText(item.answers[0], item.pinyin, 'courseInput', item.answers);
  }

  function checkText(answer, pinyin, inputId, accepted = [answer]) {
    const value = document.getElementById(inputId).value;
    const ok = accepted.some(x => norm(x) === norm(value)); markResult(ok);
    const chosen = [...wordById.values()].find(x => value.includes(x.hanzi));
    document.getElementById('courseFeedback').innerHTML = `<div class="course-feedback ${ok ? 'ok' : 'bad'}"><b>${ok ? 'Верно' : 'Нужно исправить'}</b>${!ok && chosen ? `<div>В вашем ответе: ${esc(chosen.hanzi)} · <span class="course-pinyin">${esc(chosen.pinyin)}</span></div>` : ''}<div>Правильно: ${esc(answer)}</div><div class="course-pinyin">${esc(pinyin)}</div></div>${nextButton()}`; wireNext();
  }

  function renderActive(content, step) {
    const item = step.item;
    content.innerHTML = `<div class="course-skill">Воспроизведение</div><h2>${esc(item.prompt_ru)}</h2><textarea class="course-input" id="courseInput" rows="3" lang="zh" autocomplete="off" placeholder="Напишите фразу иероглифами"></textarea><button class="course-next" id="courseCheck">Проверить</button><div id="courseFeedback"></div>`;
    document.getElementById('courseCheck').onclick = () => {
      const value = document.getElementById('courseInput').value.trim();
      const ok = norm(value) === norm(item.sample_cn); markResult(ok, 'active_speech');
      document.getElementById('courseCheck').disabled = true;
      document.getElementById('courseFeedback').innerHTML = `<div class="course-feedback ${ok ? 'ok' : 'bad'}"><b>${ok ? 'Фраза восстановлена' : 'Ответ не совпал'}</b>${!ok && value ? `<div>Ваш ответ: ${esc(value)}</div>` : ''}<div class="course-context">${esc(item.sample_cn)}</div><div class="course-pinyin">${esc(item.sample_pinyin)}</div></div>${nextButton()}`;
      wireNext();
    };
  }

  function renderGrammarReview(content, step) {
    const g = step.grammar;
    const options = shuffled(unique([g.pattern, ...shuffled([...grammarById.values()].filter(x => x.id !== g.id)).slice(0, 3).map(x => x.pattern)])).slice(0, 4);
    renderOptions(content, `<div class="course-skill">Грамматика · повторение</div><h2>${esc(g.title)}</h2><p>${esc(g.explanation_ru)}</p>`, options, g.pattern, null, g.explanation_ru, step);
  }

  function renderUnsupported(content) { content.innerHTML = `<p>Этот этап недоступен.</p>${nextButton()}`; wireNext(); }

  let activeUtterance = null;
  function showAudioStatus(message, error = false) {
    let status = document.getElementById('courseAudioStatus');
    if (!status) {
      status = document.createElement('div'); status.id = 'courseAudioStatus';
      const anchor = document.activeElement?.closest?.('.course-answer-actions') || document.activeElement;
      if (anchor?.parentNode) anchor.insertAdjacentElement('afterend', status);
    }
    if (!status) return;
    status.className = `course-audio-status${error ? ' error' : ''}`; status.textContent = message;
  }
  function speak(text, rate = .82) {
    const phrase = String(text || '').trim();
    if (!phrase) return;
    if (window.NativeSpeech?.speak) {
      try { if (window.NativeSpeech.speak(phrase, Number(rate)) !== false) { showAudioStatus('Воспроизвожу…'); return; } }
      catch (_) {}
    }
    if (!('speechSynthesis' in window) || typeof SpeechSynthesisUtterance === 'undefined') {
      showAudioStatus('Озвучивание недоступно. Включите синтез речи в настройках телефона.', true); return;
    }
    const synth = window.speechSynthesis;
    synth.cancel();
    const utterance = new SpeechSynthesisUtterance(phrase); activeUtterance = utterance;
    utterance.lang = 'zh-CN'; utterance.rate = Number(rate) || .82; utterance.volume = 1;
    const voice = synth.getVoices().find(item => /^zh(?:-|_)/i.test(item.lang)) || synth.getVoices().find(item => /^zh/i.test(item.lang));
    if (voice) utterance.voice = voice;
    utterance.onstart = () => showAudioStatus('Воспроизвожу…');
    utterance.onend = () => { activeUtterance = null; showAudioStatus('Можно прослушать ещё раз'); };
    utterance.onerror = event => { activeUtterance = null; showAudioStatus(event.error === 'not-allowed' ? 'Нажмите кнопку ещё раз — браузер заблокировал автоматический звук.' : 'Не удалось запустить звук. Проверьте синтез речи на телефоне.', true); };
    synth.resume(); synth.speak(utterance);
    setTimeout(() => { if (synth.paused) synth.resume(); }, 250);
  }

  function runtimeWord(word) { return WORDS.find(x => String(x.id) === String(word.id)); }
  function gradeRuntimeWord(word, ok = true) {
    const runtime = runtimeWord(word); if (!runtime) return;
    try { gradeWord(runtime, ok ? 'good' : 'bad', 'curriculum-review'); } catch (_) {
      const item = ws(runtime.id); item.seen = (item.seen || 0) + 1; item.last = nowMs(); item.due = nowMs() + (ok ? DAY : 10 * 60000);
    }
  }

  function gradeGrammar(id, ok = true) {
    const course = ensureCourseState(), old = course.grammarSrs[id] || { reps: 0, interval: 0, lapses: 0 };
    old.reps = Number(old.reps || 0) + 1; old.last = nowMs();
    if (ok) old.interval = Math.min(90, Math.max(1, Number(old.interval || 0) * 2 || 1));
    else { old.interval = 0; old.lapses = Number(old.lapses || 0) + 1; }
    old.due = nowMs() + (ok ? old.interval * DAY : 10 * 60000);
    course.grammarSrs[id] = old; persistCourse();
  }

  function finishLesson() {
    const course = ensureCourseState();
    if (active.type === 'lesson') {
      for (const word of active.vocabulary || []) {
        const attempt = activeStats.wordAttempts[word.id];
        gradeRuntimeWord(word, attempt ? attempt.correct / attempt.total >= .6 : true);
      }
      if (active.grammar) {
        const attempt = activeStats.grammarAttempts[active.grammar.id];
        gradeGrammar(active.grammar.id, attempt ? attempt.correct / attempt.total >= .6 : true);
      }
    }
    if (active.type !== 'session-review') {
      course.completed[active.id] = nowMs();
      course.lessonResults[active.id] = {
        completedAt: nowMs(), correct: activeStats.correct, total: activeStats.total,
        skills: JSON.parse(JSON.stringify(activeStats.skills)),
      };
      const list = levelLessons(active.hsk_level), index = list.findIndex(x => x.id === active.id);
      const following = list.slice(index + 1).find(x => !isComplete(x.id));
      if (following) course.currentByLevel[String(active.hsk_level)] = following.id;
    }
    persistCourse();
    const skillLabels = { recognition: 'узнавание', listening: 'аудирование', grammar: 'грамматика', reading: 'чтение', word_order: 'порядок слов', fill_blank: 'пропуски', translation: 'перевод', active_speech: 'воспроизведение фразы' };
    const weak = Object.entries(activeStats.skills)
      .filter(([, item]) => item.total && item.correct / item.total < .6)
      .map(([skill]) => skillLabels[skill] || skill);
    const resultNote = weak.length
      ? `На повторение поставлены: ${weak.join(', ')}. Ошибочные задания уже встретились ещё раз в конце занятия.`
      : 'Все проверенные навыки в норме; следующий повтор будет по расписанию.';
    const next = currentLesson(course.startLevel);
    document.getElementById('courseProgress').style.width = '100%';
    document.getElementById('coursePhase').innerHTML = '<div class="eyebrow">Урок завершён</div>';
    document.getElementById('courseContent').innerHTML = `<div class="course-summary"><div class="seal">好</div><h2>${esc(active.title)} — готово</h2><p>${activeStats.total ? `Правильных ответов: ${activeStats.correct} из ${activeStats.total}.` : 'Контрольное повторение завершено.'}</p><p>${esc(resultNote)}</p><div class="course-actions" style="justify-content:center"><button class="primary" id="courseFinish">На главную</button>${next && next.id !== active.id ? '<button class="ghost" id="courseNextLesson">Следующий урок</button>' : ''}</div></div>`;
    document.getElementById('courseFinish').onclick = () => { closeLesson(); renderAllViews(); showView('today'); };
    const nextButtonEl = document.getElementById('courseNextLesson');
    if (nextButtonEl) nextButtonEl.onclick = () => startLesson(next.id);
  }

  function startCourseReview() {
    const words = shuffled(dueVocabulary()).slice(0, 8).map(runtime => wordById.get(String(runtime.id))).filter(Boolean);
    const dueGrammars = shuffled(dueGrammar());
    if (!words.length && !dueGrammars.length) {
      const lesson = currentLesson(); if (lesson) startLesson(lesson.id); return;
    }
    const currentLevel = ensureCourseState().startLevel;
    const completedContexts = shuffled(lessons
      .filter(lesson => lesson.hsk_level === currentLevel && isComplete(lesson.id))
      .flatMap(lesson => lesson.contexts || []));
    const seenContexts = new Set();
    const contexts = [...words.map(contextForWord).filter(Boolean), ...completedContexts]
      .filter(context => !seenContexts.has(context.source_sentence_id) && seenContexts.add(context.source_sentence_id));
    const grammar = dueGrammars[0] || shuffled(lessons
      .filter(lesson => lesson.hsk_level === currentLevel && isComplete(lesson.id) && lesson.grammar)
      .map(lesson => lesson.grammar))[0];
    active = { id: 'course-review', type: 'session-review', hsk_level: ensureCourseState().startLevel, title: 'Интервальное повторение' };
    if (contexts.length >= 3 && grammar) {
      const [first, second, third] = contexts;
      activeSteps = [
        { type: 'context-listening', context: first, word: contextWord(first), skill: 'listening', review: true },
        { type: 'ru-hanzi', word: contextWord(second), skill: 'recognition', review: true },
        { type: 'grammar-review', grammar, skill: 'grammar', review: true },
        { type: 'context-reading', context: second, word: contextWord(second), skill: 'reading', review: true },
        { type: 'context-order', context: third, word: contextWord(third), skill: 'word_order', review: true },
        { type: 'context-production', context: first, word: contextWord(first), skill: 'active_speech', review: true },
      ].filter(step => !('word' in step) || step.word);
    } else {
      activeSteps = [
        ...words.slice(0, 5).map((word, index) => ({ type: index % 3 === 0 ? 'listening-word' : index % 2 ? 'ru-hanzi' : 'hanzi-ru', word, skill: index % 3 === 0 ? 'listening' : 'recognition', review: true })),
        ...(grammar ? [{ type: 'grammar-review', grammar, skill: 'grammar', review: true }] : []),
      ];
    }
    activePos = 0; activeStats = { correct: 0, total: 0, skills: {}, wordAttempts: {}, grammarAttempts: {}, retryKeys: new Set() };
    makeModal(); document.getElementById('courseModal').classList.add('open'); renderStep();
  }

  function showOnboarding(settings = false) {
    let overlay = document.getElementById('courseOnboarding');
    if (!overlay) {
      overlay = document.createElement('div'); overlay.id = 'courseOnboarding'; overlay.className = 'course-onboarding'; document.body.appendChild(overlay);
    }
    overlay.innerHTML = `<div class="course-onboarding-box"><div class="eyebrow">Chinese Study · Curriculum 1.1</div><h1>${settings ? 'Выберите текущий уровень' : 'С какого уровня начать?'}</h1><p>Тестирование не требуется. Выбор можно изменить позже; ваши материалы, слова и история занятий сохранятся.</p><div class="course-level-choice">${levels.map(level => `<button data-level="${level.hsk_level}"><b>HSK ${level.hsk_level}</b><small>${level.units.length} разделов · ${levelLessons(level.hsk_level).length} уроков</small></button>`).join('')}</div>${settings ? '<button class="ghost" id="courseCancelSettings" style="margin-top:12px">Отмена</button>' : ''}</div>`;
    overlay.querySelectorAll('[data-level]').forEach(button => button.onclick = () => {
      const course = ensureCourseState(); course.startLevel = Number(button.dataset.level); persistCourse(); overlay.remove(); renderAllViews();
    });
    const cancel = overlay.querySelector('#courseCancelSettings'); if (cancel) cancel.onclick = () => overlay.remove();
  }

  function renderAllViews() { renderCourseHome(); renderCourseRoad(); }

  function annotateMaterialPreview() {
    const preview = document.getElementById('aimPreview');
    if (!preview) return;
    const cards = [...preview.querySelectorAll('.aim-word')];
    if (!cards.length) return;
    const signature = cards.map(card => card.querySelector('b')?.textContent?.trim() || '').join('|');
    if (preview.dataset.curriculumSignature === signature) return;
    const course = ensureCourseState();
    const selectedLevel = Number(course.startLevel || 1);
    const upcomingLessons = levelLessons(selectedLevel).filter(x => !isComplete(x.id)).slice(0, 4);
    const upcoming = new Set(upcomingLessons.flatMap(x => x.vocabulary || []).map(x => x.hanzi));
    const knownHanzi = new Set();
    for (const [id, progress] of Object.entries(state.words || {})) {
      if (Number(progress?.seen || 0) > 0 && wordById.has(id)) knownHanzi.add(wordById.get(id).hanzi);
    }
    for (const word of state.customWords || []) if (Number(state.words?.[word.id]?.seen || 0) > 0) knownHanzi.add(word.h || word.hanzi);
    const counts = { known: 0, upcoming: 0, fresh: 0 };
    const wordsMode = document.querySelector('#aiMatModal input[name="aimStudyMode"]:checked')?.value === 'words';
    for (const card of cards) {
      const hanzi = card.querySelector('b')?.textContent?.trim() || '';
      let kind = 'fresh', label = 'новое';
      if (knownHanzi.has(hanzi)) { kind = 'known'; label = 'уже изучалось'; }
      else if (upcoming.has(hanzi)) { kind = 'upcoming'; label = 'в ближайших уроках'; }
      counts[kind]++;
      const badge = document.createElement('em');
      badge.textContent = label; badge.style.cssText = 'grid-column:2;font:700 10px system-ui;color:var(--accent,#98622f)';
      card.appendChild(badge);
      if (wordsMode && kind !== 'fresh') {
        const checkbox = card.querySelector('input[type="checkbox"]');
        if (checkbox) checkbox.checked = false;
      }
    }
    const summary = document.createElement('div');
    summary.className = 'card'; summary.style.cssText = 'margin:12px 0;padding:13px';
    summary.innerHTML = `<b>В материале ${cards.length} слов</b><div class="course-meta" style="margin-top:8px"><span>${counts.known} уже изучались</span><span>${counts.upcoming} входят в ближайшие уроки</span><span>${counts.fresh} новых</span></div>${wordsMode ? `<small style="display:block;margin-top:8px">Для режима «Только новые слова» выбраны ${counts.fresh} действительно новых слов. Грамматика материала в Curriculum не добавляется.</small>` : '<small style="display:block;margin-top:8px">Полная тема останется личным материалом и не изменит грамматическую последовательность Curriculum.</small>'}`;
    const heading = preview.querySelector('h3');
    if (heading) preview.insertBefore(summary, heading); else preview.prepend(summary);
    preview.dataset.curriculumSignature = signature;
  }

  function watchMaterialPreview() {
    const preview = document.getElementById('aimPreview');
    if (!preview) return;
    new MutationObserver(mutations => {
      if (mutations.some(m => [...m.addedNodes].some(node => node.nodeType === 1 && node.classList?.contains('aim-title')))) preview.dataset.curriculumSignature = '';
      queueMicrotask(annotateMaterialPreview);
    }).observe(preview, { childList: true });
  }

  async function checkClientVersion() {
    try {
      const response = await fetch('api/health', { cache: 'no-store' });
      const health = response.ok ? await response.json() : null;
      if (!health?.version || CLIENT_VERSION === 'dev' || health.version === CLIENT_VERSION || document.getElementById('courseUpdateNotice')) return;
      const notice = document.createElement('div'); notice.id = 'courseUpdateNotice';
      notice.style.cssText = 'position:fixed;left:12px;right:12px;bottom:12px;z-index:13000;padding:13px 16px;border-radius:13px;background:#25322d;color:#fff;display:flex;gap:12px;align-items:center;justify-content:space-between;box-shadow:0 12px 35px #0006';
      notice.innerHTML = '<b>Доступна новая версия упражнений</b><button style="padding:9px 13px;border:0;border-radius:9px;font-weight:800;cursor:pointer">Обновить</button>';
      notice.querySelector('button').onclick = () => location.reload(); document.body.appendChild(notice);
    } catch (_) {}
  }

  async function boot() {
    try {
      window.CHINESE_CURRICULUM_CLIENT_VERSION = CLIENT_VERSION;
      const response = await fetch(CURRICULUM_URL, { cache: 'no-store' });
      if (!response.ok) throw new Error(`Curriculum ${response.status}`);
      indexCurriculum(await response.json());
      ensureCourseState(); hydrateRuntimeWords(); injectStyles(); addCourseView(); makeModal();
      const originalRenderToday = window.renderToday;
      if (typeof originalRenderToday === 'function') window.renderToday = function () { originalRenderToday(); renderCourseHome(); };
      renderAllViews(); watchMaterialPreview();
      checkClientVersion(); setInterval(checkClientVersion, 5 * 60 * 1000);
      if (!ensureCourseState().startLevel) showOnboarding(false);
    } catch (error) {
      console.error('Curriculum load failed', error);
      document.documentElement.dataset.curriculum = 'error';
    }
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot, { once: true }); else boot();
})();
