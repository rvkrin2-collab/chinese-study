#!/usr/bin/env bash
set -euo pipefail

if [ "${EUID:-$(id -u)}" -ne 0 ]; then
  echo "Запусти от root: sudo bash install.sh"
  exit 1
fi

BASE="https://raw.githubusercontent.com/rvkrin2-collab/chinese-study/main"
APP_DIR="/opt/apps/chinese-study"
STATE_DIR="/var/lib/chinese-study"
ENV_FILE="/etc/chinese-study.env"
UPDATER="/usr/local/sbin/chinese-study-update"

need=0
for c in curl base64 gzip sha256sum python3 pdftoppm; do
  command -v "$c" >/dev/null 2>&1 || need=1
done
if [ "$need" -eq 1 ]; then
  apt-get update
  apt-get install -y curl ca-certificates coreutils gzip python3 poppler-utils
fi
mkdir -p "$APP_DIR" "$STATE_DIR"

KEY="${MINIMAX_API_KEY:-}"
API_HOST="${MINIMAX_API_HOST:-}"
MODEL="${MINIMAX_MODEL:-}"
if [ -f "$ENV_FILE" ]; then
  [ -n "$KEY" ] || KEY="$(sed -n 's/^MINIMAX_API_KEY=//p' "$ENV_FILE" | head -1)"
  [ -n "$API_HOST" ] || API_HOST="$(sed -n 's/^MINIMAX_API_HOST=//p' "$ENV_FILE" | head -1)"
  [ -n "$MODEL" ] || MODEL="$(sed -n 's/^MINIMAX_MODEL=//p' "$ENV_FILE" | head -1)"
fi
API_HOST="${API_HOST:-https://api.minimax.io}"
MODEL="${MODEL:-MiniMax-M3}"

if [ -z "$KEY" ] && [ -r /dev/tty ]; then
  echo "Для разбора материалов нужен MiniMax Token Plan API key (sk-cp-...)." >/dev/tty
  printf 'MINIMAX_API_KEY: ' >/dev/tty
  IFS= read -r -s KEY </dev/tty || true
  echo >/dev/tty
fi

cat >"$ENV_FILE" <<EOF
MINIMAX_API_KEY=$KEY
MINIMAX_API_HOST=$API_HOST
MINIMAX_MODEL=$MODEL
EOF
chmod 600 "$ENV_FILE"

cat >"$UPDATER" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
BASE="https://raw.githubusercontent.com/rvkrin2-collab/chinese-study/main"
APP_DIR="/opt/apps/chinese-study"
STATE_DIR="/var/lib/chinese-study"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

curl -fsSL --retry 3 --connect-timeout 10 "$BASE/manifest.txt" -o "$TMP/manifest.txt"
VERSION="$(awk -F= '$1=="version"{print $2}' "$TMP/manifest.txt")"
SHA="$(awk -F= '$1=="sha256"{print $2}' "$TMP/manifest.txt")"
CHUNKS="$(awk -F= '$1=="chunks"{print $2}' "$TMP/manifest.txt")"
[[ "$VERSION" =~ ^[0-9A-Za-z._-]+$ ]] || { echo "Некорректная версия" >&2; exit 1; }
[[ "$SHA" =~ ^[0-9a-f]{64}$ ]] || { echo "Некорректный SHA256" >&2; exit 1; }
[[ "$CHUNKS" =~ ^[0-9]+$ ]] || { echo "Некорректное число частей" >&2; exit 1; }
[ "$CHUNKS" -ge 1 ] && [ "$CHUNKS" -le 99 ] || exit 1

changed=0
CURRENT="$(cat "$STATE_DIR/version" 2>/dev/null || true)"
if [ "$CURRENT" != "$VERSION" ] || [ ! -s "$APP_DIR/index.html" ]; then
  : >"$TMP/payload.b64"
  for ((i=0;i<CHUNKS;i++)); do
    printf -v p '%02d' "$i"
    curl -fsSL --retry 3 --connect-timeout 10 "$BASE/dist/${p}.txt" >>"$TMP/payload.b64"
  done
  base64 -d "$TMP/payload.b64" | gzip -dc >"$TMP/index.html"
  printf '%s  %s\n' "$SHA" "$TMP/index.html" | sha256sum -c - >/dev/null
  grep -qi '<!doctype html' "$TMP/index.html"
  [ "$(wc -c <"$TMP/index.html")" -gt 10000 ]
  python3 - "$TMP/index.html" "$VERSION" <<'PY'
import re,sys
p,version=sys.argv[1],sys.argv[2]
s=open(p,encoding='utf-8').read()
s=re.sub(r'<script src="ai-import\.js\?v=[^"]+"></script>\s*','',s)
s=s.replace('</body>',f'<script src="ai-import.js?v={version}"></script>\n</body>')
open(p,'w',encoding='utf-8').write(s)
PY
  install -m 0644 "$TMP/index.html" "$APP_DIR/index.html.new"
  mv -f "$APP_DIR/index.html.new" "$APP_DIR/index.html"
  printf '%s\n' "$VERSION" >"$STATE_DIR/version"
  changed=1
fi

for f in server.py ai-import.js; do
  curl -fsSL --retry 3 --connect-timeout 10 "$BASE/$f" -o "$TMP/$f"
  if ! cmp -s "$TMP/$f" "$APP_DIR/$f" 2>/dev/null; then
    install -m 0644 "$TMP/$f" "$APP_DIR/$f"
    changed=1
  fi
done

if [ "$changed" -eq 1 ] && systemctl is-active chinese-study.service >/dev/null 2>&1; then
  systemctl restart chinese-study.service
fi
echo "Chinese Study: версия $VERSION актуальна"
EOF
chmod 0755 "$UPDATER"

cat >/etc/systemd/system/chinese-study.service <<'EOF'
[Unit]
Description=Chinese Study website and MiniMax material analyzer
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
EnvironmentFile=-/etc/chinese-study.env
Environment=CHINESE_STUDY_DIR=/opt/apps/chinese-study
ExecStart=/usr/bin/python3 /opt/apps/chinese-study/server.py
Restart=always
RestartSec=2
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

cat >/etc/systemd/system/chinese-study-update.service <<'EOF'
[Unit]
Description=Update Chinese Study from GitHub
After=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/chinese-study-update
EOF

cat >/etc/systemd/system/chinese-study-update.timer <<'EOF'
[Unit]
Description=Check Chinese Study updates

[Timer]
OnBootSec=30s
OnUnitActiveSec=60s
Persistent=true
Unit=chinese-study-update.service

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl stop chinese-study-update.timer 2>/dev/null || true
"$UPDATER"
systemctl enable chinese-study.service chinese-study-update.timer >/dev/null
systemctl restart chinese-study.service
systemctl start chinese-study-update.timer
sleep 1

echo
curl -fsS http://127.0.0.1:8910/api/health
echo
echo "Готово. Chinese Study + MiniMax работают на 127.0.0.1:8910"
