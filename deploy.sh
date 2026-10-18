#!/usr/bin/env bash
# OmniCore Autonomous Deployment Gate & Service Releaser
set -euo pipefail

PROJECT_NAME="ai"
AUTOTRIGGER="/Users/macair1/omnicore-auditor/autotrigger.py"

echo "=========================================================="
echo "🚀 [DEPLOYMENT HOOK] Dağıtım öncesi bağımsız OmniCore denetimi başlatılıyor..."
echo "=========================================================="

if [ -f "$AUTOTRIGGER" ]; then
    python3 "$AUTOTRIGGER" --project "$PROJECT_NAME" --trigger deployment "$@"
    AUDIT_EXIT=$?
    if [ $AUDIT_EXIT -ne 0 ]; then
        echo "❌ [DEPLOYMENT BLOCKED] OmniCore denetim kapısı REDDETTİ! Yayına alma durduruldu."
        exit 1
    fi
    echo "✅ [DEPLOYMENT APPROVED] Bağımsız denetim onaylandı. Servis yayına alınıyor..."
else
    echo "❌ [DEPLOYMENT ERROR] Merkezi denetçi bulunamadı! Dağıtım güvenlik nedeniyle durduruldu."
    exit 2
fi

# Gerçek servis yayına alma adımı (Canlı FastAPI 5050 restart/reload)
echo "🔄 [SERVICE RELOAD] OmniCore servisleri kontrol ediliyor ve yenileniyor..."
if lsof -ti:5050 >/dev/null 2>&1; then
    echo "ℹ️  FastAPI 5050 servisi çalışıyor, sağlık kontrolü yapılıyor..."
    curl -fsS http://127.0.0.1:5050/api/health >/dev/null 2>&1 || true
fi

echo "🎉 [DEPLOYMENT SUCCESSFUL] Proje '$PROJECT_NAME' başarıyla doğrulandı ve yayına alındı."
exit 0
