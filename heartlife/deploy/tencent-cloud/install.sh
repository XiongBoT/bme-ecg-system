#!/usr/bin/env bash
set -euo pipefail

# HeartLife (心伴) 腾讯云 Ubuntu 24.04 一键构建与用户级服务安装脚本
# 默认代码目录: ~/heartlife
# 默认数据目录: ~/heartlife-data (与代码解耦，升级不覆盖数据)
# 默认监听地址: 127.0.0.1:8010 (与原心电云端平台 127.0.0.1:8766 完全隔离)

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${HEARTLIFE_DATA_DIR:-$HOME/heartlife-data}"
ENV_FILE="$DATA_DIR/heartlife.env"
SYSTEMD_USER_DIR="$HOME/.config/systemd/user"

echo "==> [1/5] 准备独立数据目录: $DATA_DIR"
mkdir -p "$DATA_DIR"
chmod 700 "$DATA_DIR"

if [ ! -f "$ENV_FILE" ]; then
  SECRET_VAL="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
  cat > "$ENV_FILE" <<EOF
APP_ENV=production
APP_HOST=127.0.0.1
APP_PORT=8010
DATABASE_URL=sqlite:///${DATA_DIR}/heartlife.db
SESSION_SECRET=${SECRET_VAL}
COOKIE_SECURE=true
DEMO_MODE=false
ASSISTANT_ENABLED=true
ASSISTANT_PROVIDER=deterministic
# 可按需指向已部署的心电云端工作台静态 HTTPS 入口（不含参数）
ECG_EXTERNAL_URL=https://62.234.150.104/
FRONTEND_ORIGIN=https://62.234.150.104
EOF
  chmod 600 "$ENV_FILE"
  echo "    已生成首次生产配置文件: $ENV_FILE （请按实际域名或公网 IP 核对 FRONTEND_ORIGIN）"
else
  echo "    检测到已有配置文件 $ENV_FILE，保留现有密钥与配置。"
fi

echo "==> [2/5] 创建独立 Python 虚拟环境并安装后端依赖"
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/python" -m pip install --upgrade pip
"$APP_DIR/.venv/bin/python" -m pip install -r "$APP_DIR/backend/requirements.txt"

echo "==> [3/5] 安装前端依赖并构建适老化生产静态资源 (frontend/dist)"
cd "$APP_DIR/frontend"
npm ci
npm run build

echo "==> [4/5] 执行 Alembic 数据库迁移"
cd "$APP_DIR/backend"
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a
"$APP_DIR/.venv/bin/python" -c "from app.core.config import get_settings; from app.db.migrations_runner import run_migrations; run_migrations(get_settings().database_url)"

echo "==> [5/5] 安装 systemd 用户级服务 (~/.config/systemd/user/heartlife.service)"
mkdir -p "$SYSTEMD_USER_DIR"
sed \
  -e "s|__APP_DIR__|${APP_DIR}|g" \
  -e "s|__ENV_FILE__|${ENV_FILE}|g" \
  "$APP_DIR/deploy/tencent-cloud/heartlife.service" > "$SYSTEMD_USER_DIR/heartlife.service"

echo "安装完成！请依次执行以下命令启动并验证："
echo "  systemctl --user daemon-reload"
echo "  systemctl --user enable --now heartlife.service"
echo "  curl --fail http://127.0.0.1:8010/api/v1/health"
