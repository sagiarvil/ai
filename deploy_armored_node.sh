#!/bin/zsh
# ==============================================================================
# MISTRAL-24B-ABLITERATED: TAHKİMAT PAKETİ (LEGACY)
# ==============================================================================

if [[ "$1" != "--apply" && "$1" != "--confirm" ]]; then
    echo "Eski kurulum betiği doğrudan çalıştırılmadı; --apply bayrağı gereklidir."
    exit 2
fi

set -e


TARGET_USER="$(logname 2>/dev/null || echo $USER)"
USER_HOME="/Users/${TARGET_USER}"
LLAMA_BIN="/opt/homebrew/bin/llama-server"
MODEL_PATH="${USER_HOME}/models/huihui-ai_Mistral-Small-24B-Instruct-2501-abliterated-Q4_K_M.gguf"
CACHE_DIR="${USER_HOME}/models/prompt_cache"
LOG_FILE="/var/log/mistral_tactical_node.log"
ERR_FILE="/var/log/mistral_tactical_node.err"
PLIST_PATH="/Library/LaunchDaemons/com.tactical.mistral24b.plist"
PF_ANCHOR="/etc/pf.anchors/com.tactical.airgap"

echo "[1/5] Dizinler ve Prompt Cache alanı hazırlanıyor..."
mkdir -p "$CACHE_DIR"
chown -R "${TARGET_USER}:staff" "$CACHE_DIR"
touch "$LOG_FILE" "$ERR_FILE"
chown "${TARGET_USER}:wheel" "$LOG_FILE" "$ERR_FILE"

echo "[2/5] Metal GPU VRAM Limiti (20 GB) çekirdek seviyesinde sabitleniyor..."
sysctl iogpu.wired_limit_mb=20480 || true
if [ -f /etc/sysctl.conf ]; then
    if ! grep -q "iogpu.wired_limit_mb" /etc/sysctl.conf 2>/dev/null; then
        echo "iogpu.wired_limit_mb=20480" >> /etc/sysctl.conf
    fi
else
    echo "iogpu.wired_limit_mb=20480" > /etc/sysctl.conf
fi

echo "[3/5] Kernel Packet Filter (pfctl) Air-Gap Firewall kuralları yazılıyor..."
mkdir -p /etc/pf.anchors
cat << 'EOF' > "$PF_ANCHOR"
# Tactical Air-Gap Rules for Local LLM Node (Port 8080)
block drop in quick on ! lo0 proto { tcp, udp } from any to any port 8080
block drop out quick on ! lo0 proto { tcp, udp } from any port 8080 to any
pass in quick on lo0 proto tcp from 127.0.0.1 to 127.0.0.1 port 8080
EOF

if ! grep -q "com.tactical.airgap" /etc/pf.conf 2>/dev/null; then
    cp /etc/pf.conf /etc/pf.conf.bak 2>/dev/null || true
    echo 'anchor "com.tactical.airgap"' >> /etc/pf.conf
    echo 'load anchor "com.tactical.airgap" from "/etc/pf.anchors/com.tactical.airgap"' >> /etc/pf.conf
fi
pfctl -f /etc/pf.conf 2>/dev/null || true
pfctl -E 2>/dev/null || true

echo "[4/5] Askeri Sınıf LaunchDaemon (Watchdog & Self-Healing) servisi oluşturuluyor..."
cat << EOF > "$PLIST_PATH"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.tactical.mistral24b</string>

    <key>UserName</key>
    <string>${TARGET_USER}</string>

    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/caffeinate</string>
        <string>-dimsu</string>
        <string>${LLAMA_BIN}</string>
        <string>--model</string>
        <string>${MODEL_PATH}</string>
        <string>--ctx-size</string>
        <string>16384</string>
        <string>--n-gpu-layers</string>
        <string>99</string>
        <string>--mlock</string>
        <string>--flash-attn</string>
        <string>--cache-type-k</string>
        <string>q8_0</string>
        <string>--cache-type-v</string>
        <string>q8_0</string>
        <string>--parallel</string>
        <string>1</string>
        <string>--cont-batching</string>
        <string>--seed</string>
        <string>42</string>
        <string>--temp</string>
        <string>0.0</string>
        <string>--dry-multiplier</string>
        <string>0.8</string>
        <string>--slot-save-path</string>
        <string>${CACHE_DIR}</string>
        <string>--jinja</string>
        <string>--host</string>
        <string>127.0.0.1</string>
        <string>--port</string>
        <string>8080</string>
    </array>

    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
        <key>Crashed</key>
        <true/>
    </dict>
    <key>ThrottleInterval</key>
    <integer>2</integer>

    <key>ProcessType</key>
    <string>Interactive</string>
    <key>Nice</key>
    <integer>-10</integer>
    <key>AbandonProcessGroup</key>
    <true/>

    <key>SoftResourceLimits</key>
    <dict>
        <key>NumberOfFiles</key>
        <integer>65536</integer>
    </dict>
    <key>HardResourceLimits</key>
    <dict>
        <key>NumberOfFiles</key>
        <integer>65536</integer>
    </dict>

    <key>StandardOutPath</key>
    <string>${LOG_FILE}</string>
    <key>StandardErrorPath</key>
    <string>${ERR_FILE}</string>
</dict>
</plist>
EOF

echo "[5/5] İzinler mühürleniyor ve servis ateşleniyor..."
chown root:wheel "$PLIST_PATH"
chmod 644 "$PLIST_PATH"

launchctl bootout system "$PLIST_PATH" 2>/dev/null || true
launchctl bootstrap system "$PLIST_PATH" 2>/dev/null || true
launchctl enable system/com.tactical.mistral24b 2>/dev/null || true
launchctl kickstart -k system/com.tactical.mistral24b 2>/dev/null || true

echo "===================================================================="
echo "[OK] ZIRHLI MISTRAL-24B DÜĞÜMÜ AKTİF (127.0.0.1:8080 - AIR-GAPPED)"
echo "Log Takibi : tail -f ${ERR_FILE}"
echo "Durum      : sudo launchctl print system/com.tactical.mistral24b"
echo "===================================================================="
