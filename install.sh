#!/usr/bin/env bash
set -euo pipefail

if [ "${EUID:-$(id -u)}" -ne 0 ]; then
  echo "Запусти от root: sudo bash install.sh"
  exit 1
fi

REPO="rvkrin2-collab/chinese-study"
BASE="https://raw.githubusercontent.com/${REPO}/main"
APP_DIR="/opt/apps/chinese-study"
STATE_DIR="/var/lib/chinese-study"
UPDATER="/usr/local/sbin/chinese-study-update"

need_install=0
for cmd in curl base64 gzip sha256sum python3; do
  command -v "$cmd" >/dev/null 2>&1 || need_install=1
done
if [ "$need_install" -eq 1 ]; then
  apt-get update
  apt-get install -y curl ca-certificates coreutils gzip python3
fi

mkdir -p "$APP_DIR" "$STATE_DIR"

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
[ "$CHUNKS" -ge 1 ] && [ "$CHUNKS" -le 99 ] || { echo "Некорректное число частей" >&2; exit 1; }

CURRENT="$(cat "$STATE_DIR/version" 2>/dev/null || true)"
if [ "$CURRENT" = "$VERSION" ] && [ -s "$APP_DIR/index.html" ]; then
  exit 0
fi

: > "$TMP/payload.b64"
for ((i=0; i<CHUNKS; i++)); do
  printf -v part '%02d' "$i"
  curl -fsSL --retry 3 --connect-timeout 10 "$BASE/dist/${part}.txt" >> "$TMP/payload.b64"
done

base64 -d "$TMP/payload.b64" | gzip -dc > "$TMP/index.html"
printf '%s  %s\n' "$SHA" "$TMP/index.html" | sha256sum -c - >/dev/null

grep -qi '<!doctype html' "$TMP/index.html" || { echo "Получен не HTML" >&2; exit 1; }
[ "$(wc -c < "$TMP/index.html")" -gt 10000 ] || { echo "HTML подозрительно мал" >&2; exit 1; }

install -m 0644 "$TMP/index.html" "$APP_DIR/index.html.new"
mv -f "$APP_DIR/index.html.new" "$APP_DIR/index.html"
printf '%s\n' "$VERSION" > "$STATE_DIR/version"
echo "Chinese Study обновлён до версии $VERSION"
EOF
chmod 0755 "$UPDATER"

cat >/etc/systemd/system/chinese-study-update.service <<'EOF'
[Unit]
Description=Update Chinese Study website from GitHub
After=network-online.target
Wants=network-online.target

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

PYTHON_BIN="$(command -v python3)"
cat >/etc/systemd/system/chinese-study.service <<EOF
[Unit]
Description=Chinese Study Website
After=network.target

[Service]
Type=simple
ExecStart=${PYTHON_BIN} -m http.server 8910 --bind 127.0.0.1 --directory /opt/apps/chinese-study
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl stop chinese-study-update.timer 2>/dev/null || true
"$UPDATER"
systemctl enable --now chinese-study.service
systemctl enable --now chinese-study-update.timer

sleep 1
curl -fsI http://127.0.0.1:8910/ >/dev/null

echo
echo "Готово. Установлена версия: $(cat "$STATE_DIR/version")"
echo "Локальный сайт отвечает: http://127.0.0.1:8910/"
echo "Tailscale-маршрут не изменялся."
