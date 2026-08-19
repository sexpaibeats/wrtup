#!/bin/sh
# ============================================================================
#  router-setup.sh
#  Универсальный скрипт первичной настройки роутеров на OpenWrt / ImmortalWrt
#  и прошивках GL.iNet (поддержка apk и opkg, 24.10 / 25.12+).
#
#  Проверялся на: GL.iNet Flint 2 (GL-MT6000), Xiaomi/Redmi AX6S (ImmortalWrt).
#  Должен корректно работать на любом устройстве OpenWrt/ImmortalWrt.
#
#  Запуск одной командой:
#     sh <(wget -O - https://raw.githubusercontent.com/<user>/<repo>/main/router-setup.sh)
#  Внимание: конструкция sh <(...) требует bash. На самом роутере (ash) так
#  не сработает, поэтому лучше:
#     wget -O /tmp/router-setup.sh https://raw.githubusercontent.com/<user>/<repo>/main/router-setup.sh
#     sh /tmp/router-setup.sh
#
#  Скрипт идемпотентен — безопасно запускать повторно. Каждый шаг сначала
#  проверяет, не выполнен ли он уже, и либо пропускает его, либо предлагает
#  повторить/пересоздать. Все опасные и «вкусовые» изменения (governor,
#  сетевые твики, репозиторий ImmortalWrt и т.д.) подтверждаются вопросом
#  с объяснением, зачем это нужно.
#
#  Лицензия: делайте с этим скриптом что хотите.
# ============================================================================

set -u

# ---------------------------------------------------------------------------
# Базовая настройка: лог, цвета
# ---------------------------------------------------------------------------

SCRIPT_VERSION="1.0"
LOG="/root/router-setup-$(date +%Y%m%d-%H%M%S 2>/dev/null || echo run).log"
: > "$LOG" 2>/dev/null || LOG="/tmp/router-setup.log"
: > "$LOG" 2>/dev/null

IMMORTAL_MIRROR="https://mirrors.vsean.net/openwrt/releases"

if [ -t 1 ]; then
  C_RESET='\033[0m'; C_RED='\033[31m'; C_GREEN='\033[32m'
  C_YELLOW='\033[33m'; C_BLUE='\033[34m'; C_CYAN='\033[36m'; C_BOLD='\033[1m'
else
  C_RESET=''; C_RED=''; C_GREEN=''; C_YELLOW=''; C_BLUE=''; C_CYAN=''; C_BOLD=''
fi

pkg_updated=0

trap 'rm -f /tmp/forkop_install.sh /tmp/footstrap_install.sh /tmp/luci-app-temp-status.* 2>/dev/null' EXIT

# ---------------------------------------------------------------------------
# Вывод / лог
# ---------------------------------------------------------------------------

_log_plain() { printf '%s\n' "$1" >> "$LOG" 2>/dev/null; }
ok()      { printf '%b✔ %s%b\n'  "$C_GREEN"  "$1" "$C_RESET"; _log_plain "[OK]   $1"; }
warn()    { printf '%b⚠ %s%b\n'  "$C_YELLOW" "$1" "$C_RESET"; _log_plain "[WARN] $1"; }
err()     { printf '%b✘ %s%b\n'  "$C_RED"    "$1" "$C_RESET"; _log_plain "[ERR]  $1"; }
info()    { printf '%b• %s%b\n'  "$C_CYAN"   "$1" "$C_RESET"; _log_plain "[INFO] $1"; }
skip()    { printf '%b— %s (пропущено)%b\n' "$C_BLUE" "$1" "$C_RESET"; _log_plain "[SKIP] $1"; }
section() { printf '\n%b=== %s ===%b\n' "$C_BOLD" "$1" "$C_RESET"; _log_plain ""; _log_plain "=== $1 ==="; }

ask_yn() {
  # $1 = вопрос, $2 = default y/n
  q="$1"; def="${2:-n}"
  if [ -r /dev/tty ]; then
    if [ "$def" = "y" ]; then hint="[Y/n]"; else hint="[y/N]"; fi
    printf '%b?%b %s %s: ' "$C_YELLOW" "$C_RESET" "$q" "$hint" > /dev/tty
    read -r ans < /dev/tty
    ans="${ans:-$def}"
    case "$ans" in
      y|Y|yes|Yes|YES|д|Д|да|Да|ДА) return 0 ;;
      *) return 1 ;;
    esac
  else
    warn "Нет доступа к терминалу для вопроса «$q» — используется значение по умолчанию"
    [ "$def" = "y" ] && return 0 || return 1
  fi
}

ask_val() {
  q="$1"; def="${2:-}"
  if [ -r /dev/tty ]; then
    printf '%b?%b %s%s: ' "$C_YELLOW" "$C_RESET" "$q" "${def:+ [$def]}" > /dev/tty
    read -r ans < /dev/tty
    printf '%s' "${ans:-$def}"
  else
    printf '%s' "$def"
  fi
}

# ---------------------------------------------------------------------------
# Сеть: curl если есть, иначе wget
# ---------------------------------------------------------------------------

fetch_to_stdout() {
  # $1 url  $2 timeout(сек, опционально)
  t="${2:-15}"
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL --max-time "$t" "$1" 2>>"$LOG"
  else
    wget -qO- --timeout="$t" "$1" 2>>"$LOG"
  fi
}

fetch_to_file() {
  # $1 url  $2 dest  $3 timeout(опционально)
  t="${3:-20}"
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL --max-time "$t" -o "$2" "$1" 2>>"$LOG"
  else
    wget -qO "$2" --timeout="$t" "$1" 2>>"$LOG"
  fi
}

http_exists() {
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL --max-time 8 -o /dev/null "$1" 2>>"$LOG"
  else
    wget -q --spider --timeout=8 "$1" 2>>"$LOG"
  fi
}

# ---------------------------------------------------------------------------
# Пакетный менеджер: apk / opkg
# ---------------------------------------------------------------------------

pkg_update_once() {
  [ "$pkg_updated" = "1" ] && return 0
  info "Обновление индекса пакетов ($PKG update)..."
  if [ "$PKG" = "apk" ]; then apk update >> "$LOG" 2>&1
  else opkg update >> "$LOG" 2>&1
  fi
  rc=$?
  if [ $rc -eq 0 ]; then ok "Индекс пакетов обновлён"
  else warn "$PKG update завершился с ошибкой (код $rc), см. лог"
  fi
  pkg_updated=1
}

list_installed_pkgs() {
  if [ "$PKG" = "apk" ]; then apk info 2>/dev/null
  else opkg list-installed 2>/dev/null | awk '{print $1}'
  fi
}

pkg_installed() {
  if [ "$PKG" = "apk" ]; then apk info -e "$1" >/dev/null 2>&1
  else opkg list-installed 2>/dev/null | grep -q "^$1 "
  fi
}

pkg_install() {
  # $1 = имя пакета, $2 = человекочитаемое имя (опц.)
  name="$1"; label="${2:-$1}"
  if pkg_installed "$name"; then
    skip "$label уже установлен"
    return 0
  fi
  pkg_update_once
  info "Установка: $label ($name)..."
  if [ "$PKG" = "apk" ]; then apk add "$name" >> "$LOG" 2>&1
  else opkg install "$name" >> "$LOG" 2>&1
  fi
  rc=$?
  if [ $rc -eq 0 ] && pkg_installed "$name"; then
    ok "$label установлен"; return 0
  else
    err "Не удалось установить $label (код $rc). Подробности в логе: $LOG"; return 1
  fi
}

pkg_remove() {
  name="$1"
  pkg_installed "$name" || return 0
  if [ "$PKG" = "apk" ]; then apk del "$name" >> "$LOG" 2>&1
  else opkg remove "$name" >> "$LOG" 2>&1
  fi
}

is_clean_version() {
  echo "$1" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+$'
}

# ---------------------------------------------------------------------------
# Предварительные проверки
# ---------------------------------------------------------------------------

check_root() {
  if [ "$(id -u 2>/dev/null)" != "0" ]; then
    err "Скрипт нужно запускать от root (обычно так и есть при SSH-доступе на OpenWrt)"
    exit 1
  fi
}

check_prereqs() {
  if ! command -v wget >/dev/null 2>&1 && ! command -v curl >/dev/null 2>&1; then
    err "Не найден wget или curl. Установите: opkg install wget-ssl (или apk add wget)"
    exit 1
  fi
  if ! command -v uci >/dev/null 2>&1; then
    err "Не найдена команда uci — похоже, это не OpenWrt/ImmortalWrt устройство"
    exit 1
  fi
}

check_internet() {
  section "Проверка интернет-соединения"
  if http_exists "https://downloads.openwrt.org/" || http_exists "https://www.google.com/generate_204"; then
    ok "Интернет-соединение доступно"
  else
    err "Нет доступа в интернет — большинство шагов скрипта будет пропущено или завершится ошибкой"
    ask_yn "Продолжить всё равно?" n || { echo "Прервано пользователем."; exit 1; }
  fi
}

banner() {
  printf '%b' "$C_BOLD"
  cat <<'EOF'
============================================================
   router-setup.sh — GL.iNet / OpenWrt / ImmortalWrt
============================================================
EOF
  printf '%b' "$C_RESET"
  info "Версия скрипта: $SCRIPT_VERSION"
  info "Лог выполнения: $LOG"
}

# ---------------------------------------------------------------------------
# 1. Определение системы
# ---------------------------------------------------------------------------

detect_system() {
  section "Определение системы"

  MODEL="unknown"
  [ -f /tmp/sysinfo/model ] && MODEL=$(cat /tmp/sysinfo/model 2>/dev/null)
  [ -z "$MODEL" ] && MODEL="unknown"

  DISTRIB_ID="unknown"; DISTRIB_RELEASE="unknown"; DISTRIB_TARGET="unknown"
  if [ -f /etc/openwrt_release ]; then
    # shellcheck disable=SC1091
    . /etc/openwrt_release
    DISTRIB_ID="${DISTRIB_ID:-unknown}"
    DISTRIB_RELEASE="${DISTRIB_RELEASE:-unknown}"
    DISTRIB_TARGET="${DISTRIB_TARGET:-unknown}"
  fi

  IS_GLINET="no"
  if [ -f /etc/glversion ] || [ -d /usr/share/gl-fw ] || [ -x /usr/sbin/gl_health ] || \
     echo "$DISTRIB_ID $MODEL" | grep -Eqi "gl\.inet|gl-inet"; then
    IS_GLINET="yes"
  fi

  if command -v apk >/dev/null 2>&1; then PKG="apk"
  elif command -v opkg >/dev/null 2>&1; then PKG="opkg"
  else err "Не найден пакетный менеджер apk/opkg"; exit 1
  fi

  ARCH="unknown"
  if [ -f /etc/opkg/distfeeds.conf ]; then
    ARCH=$(grep -o '/packages/[^/]*/base' /etc/opkg/distfeeds.conf 2>/dev/null | head -n1 | cut -d/ -f3)
  fi
  [ -z "$ARCH" ] && ARCH="unknown"
  if [ "$ARCH" = "unknown" ] && [ -f /etc/apk/repositories ]; then
    ARCH=$(grep -o '/packages/[^/]*/base' /etc/apk/repositories 2>/dev/null | head -n1 | cut -d/ -f3)
    [ -z "$ARCH" ] && ARCH="unknown"
  fi
  if [ "$ARCH" = "unknown" ] && command -v opkg >/dev/null 2>&1; then
    ARCH=$(opkg print-architecture 2>/dev/null | awk '{print $2}' | grep -v '^all$' | grep -v '^noarch$' | tail -n1)
    [ -z "$ARCH" ] && ARCH="unknown"
  fi

  KVER=$(uname -r 2>/dev/null)

  KMODS_DIR=""
  for f in /etc/opkg/distfeeds.conf /etc/apk/repositories; do
    [ -f "$f" ] || continue
    line=$(grep -o '/targets/[^ ]*/kmods/[^ /]*' "$f" 2>/dev/null | head -n1)
    if [ -n "$line" ]; then
      KMODS_DIR=$(echo "$line" | sed 's#.*/kmods/##')
    fi
  done

  info "Модель:            $MODEL"
  info "Прошивка:          $DISTRIB_ID $DISTRIB_RELEASE"
  info "Это GL.iNet:       $IS_GLINET"
  info "Пакетный менеджер: $PKG"
  info "Архитектура:       $ARCH"
  info "Target:            $DISTRIB_TARGET"
  info "Ядро:              $KVER"
}

# ---------------------------------------------------------------------------
# 2. Репозитории OpenWrt / ImmortalWrt
# ---------------------------------------------------------------------------

feed_add() {
  # $1 = имя фида (для opkg), $2 = url без завершающего /
  name="$1"; url="$2"
  case "$PKG" in
    apk)
      conf="/etc/apk/repositories"
      [ -f "$conf" ] || : > "$conf"
      if grep -qF "$url" "$conf" 2>/dev/null; then skip "Уже добавлено: $url"; return 0; fi
      if http_exists "$url/packages.adb"; then
        echo "$url" >> "$conf"
        ok "Добавлен репозиторий: $url"
      else
        warn "Недоступно, пропущено: $url"
      fi
      ;;
    opkg)
      conf="/etc/opkg/customfeeds.conf"
      [ -f "$conf" ] || : > "$conf"
      if grep -qF "$url" "$conf" 2>/dev/null; then skip "Уже добавлено: $url"; return 0; fi
      if http_exists "$url/Packages.gz"; then
        echo "src/gz $name $url" >> "$conf"
        ok "Добавлен репозиторий: $url"
      else
        warn "Недоступно, пропущено: $url"
      fi
      ;;
  esac
}

install_stock_openwrt_repos() {
  section "Официальные репозитории OpenWrt"

  if [ "$DISTRIB_ID" = "OpenWrt" ] && [ "$IS_GLINET" = "no" ]; then
    skip "Это уже официальная прошивка OpenWrt — свои репозитории уже подключены"
    return
  fi
  if [ "$ARCH" = "unknown" ] || [ "$DISTRIB_TARGET" = "unknown" ] || ! is_clean_version "$DISTRIB_RELEASE"; then
    warn "Не удалось определить архитектуру/target/версию прошивки — пропуск добавления репозиториев OpenWrt"
    return
  fi

  info "Даёт доступ к полному набору официальных пакетов OpenWrt"
  info "(в т.ч. тем, которых нет в прошивке GL.iNet/ImmortalWrt)."
  ask_yn "Добавить официальные репозитории OpenWrt $DISTRIB_RELEASE ($ARCH)?" y || { skip "По выбору пользователя"; return; }

  base="https://downloads.openwrt.org/releases/$DISTRIB_RELEASE"
  feed_add "owrt_target"    "$base/targets/$DISTRIB_TARGET/packages"
  feed_add "owrt_base"      "$base/packages/$ARCH/base"
  feed_add "owrt_luci"      "$base/packages/$ARCH/luci"
  feed_add "owrt_packages"  "$base/packages/$ARCH/packages"
  feed_add "owrt_routing"   "$base/packages/$ARCH/routing"
  feed_add "owrt_telephony" "$base/packages/$ARCH/telephony"
  feed_add "owrt_video"     "$base/packages/$ARCH/video"
  if [ -n "$KMODS_DIR" ]; then
    feed_add "owrt_kmods" "$base/targets/$DISTRIB_TARGET/kmods/$KMODS_DIR"
  else
    warn "Не удалось определить версию/хэш ядра — репозиторий kmods пропущен (не критично, если сторонние модули ядра не нужны)"
  fi
  pkg_updated=0
}

resolve_immortalwrt_release() {
  test_url="$IMMORTAL_MIRROR/$DISTRIB_RELEASE/targets/$DISTRIB_TARGET/packages"
  if [ "$PKG" = "apk" ]; then
    http_exists "$test_url/packages.adb" && { echo "$DISTRIB_RELEASE"; return 0; }
  else
    http_exists "$test_url/Packages.gz" && { echo "$DISTRIB_RELEASE"; return 0; }
  fi
  majmin=$(echo "$DISTRIB_RELEASE" | cut -d. -f1,2)
  listing=$(fetch_to_stdout "$IMMORTAL_MIRROR/" 15)
  best=$(echo "$listing" | grep -o "${majmin}\.[0-9]\{1,3\}" | sort -u | tail -n1)
  if [ -n "$best" ]; then echo "$best"; return 0; fi
  return 1
}

install_immortalwrt_repo() {
  section "Репозиторий ImmortalWrt (дополнительные пакеты)"

  if [ "$DISTRIB_ID" = "ImmortalWrt" ]; then
    skip "Прошивка уже ImmortalWrt — свой репозиторий уже подключён"
    return
  fi
  if [ "$ARCH" = "unknown" ] || [ "$DISTRIB_TARGET" = "unknown" ] || ! is_clean_version "$DISTRIB_RELEASE"; then
    warn "Не удалось определить архитектуру/target/версию прошивки — пропуск"
    return
  fi

  info "Репозиторий ImmortalWrt содержит дополнительные пакеты и модифицированные"
  info "версии некоторых приложений, которых нет в официальных репозиториях OpenWrt"
  info "или в прошивке GL.iNet (например расширенные версии luci-app-*)."
  ask_yn "Добавить репозиторий ImmortalWrt ($IMMORTAL_MIRROR)?" n || { skip "По выбору пользователя"; return; }

  rel=$(resolve_immortalwrt_release)
  if [ -z "$rel" ]; then
    warn "Не удалось подобрать подходящую версию ImmortalWrt на зеркале — пропуск (добавьте вручную при необходимости)"
    return
  fi
  info "Используется версия ImmortalWrt: $rel"
  base="$IMMORTAL_MIRROR/$rel"
  feed_add "immortalwrt_target"    "$base/targets/$DISTRIB_TARGET/packages"
  feed_add "immortalwrt_base"      "$base/packages/$ARCH/base"
  feed_add "immortalwrt_luci"      "$base/packages/$ARCH/luci"
  feed_add "immortalwrt_packages"  "$base/packages/$ARCH/packages"
  feed_add "immortalwrt_routing"   "$base/packages/$ARCH/routing"
  feed_add "immortalwrt_telephony" "$base/packages/$ARCH/telephony"
  # хэш kmods у ImmortalWrt отличается от официального OpenWrt — если не подойдёт,
  # feed_add сам это обнаружит (404) и пропустит без вреда
  if [ -n "$KMODS_DIR" ]; then
    feed_add "immortalwrt_kmods" "$base/targets/$DISTRIB_TARGET/kmods/$KMODS_DIR"
  fi
  pkg_updated=0
}

# ---------------------------------------------------------------------------
# 3. Русский язык
# ---------------------------------------------------------------------------

install_gl_russian_lang() {
  section "Русский язык в панели GL.iNet"
  if [ "$IS_GLINET" != "yes" ]; then
    skip "Это не прошивка GL.iNet — пункт относится только к веб-интерфейсу GL.iNet"
    return
  fi
  if [ -f /www/i18n/release.ru.json ]; then
    skip "Файл /www/i18n/release.ru.json уже установлен"
    ask_yn "Скачать заново (обновить)?" n || return
  fi
  info "Поиск последнего релиза gl-inet/router-sdk-languages..."
  api_json=$(fetch_to_stdout "https://api.github.com/repos/gl-inet/router-sdk-languages/releases/latest" 15 | tr -d '\n')
  url=$(echo "$api_json" | grep -o '"browser_download_url":"[^"]*release\.ru\.json"' | head -n1 | sed 's/.*:"//;s/"$//')
  if [ -z "$url" ]; then
    err "Не найдена ссылка на release.ru.json в последнем релизе — пропуск"
    return 1
  fi
  mkdir -p /www/i18n
  if fetch_to_file "$url" /www/i18n/release.ru.json 20; then
    chmod 644 /www/i18n/release.ru.json
    ok "release.ru.json установлен в /www/i18n/"
    info "Выберите язык в веб-интерфейсе GL.iNet: Система → Основные настройки → Язык"
  else
    err "Не удалось скачать release.ru.json"
  fi
}

install_system_ru_language() {
  section "Русский язык интерфейса LuCI (системный)"
  pkg_install "luci-i18n-base-ru" "Базовый перевод LuCI"

  info "Поиск переводов для установленных приложений LuCI..."
  installed_apps=$(list_installed_pkgs | grep '^luci-app-' | sed 's/^luci-app-//')
  translated=0
  for app in $installed_apps; do
    ru_pkg="luci-i18n-${app}-ru"
    pkg_installed "$ru_pkg" && continue
    if [ "$PKG" = "apk" ]; then
      apk add "$ru_pkg" >> "$LOG" 2>&1 && { ok "Перевод для $app установлен"; translated=$((translated + 1)); }
    else
      opkg install "$ru_pkg" >> "$LOG" 2>&1 && { ok "Перевод для $app установлен"; translated=$((translated + 1)); }
    fi
  done
  [ "$translated" = "0" ] && info "Дополнительных переводов для установленных приложений не найдено (это нормально)"

  if ask_yn "Установить русский язык интерфейса LuCI по умолчанию?" y; then
    uci set luci.main.lang='ru' 2>>"$LOG"
    uci commit luci
    ok "Язык интерфейса LuCI: ru"
  fi

  section "Удаление китайского перевода (оставить только ru/en)"
  zh_pkgs=$(list_installed_pkgs | grep -E -- '-zh(-cn|_Hans[a-zA-Z_]*)?$')
  if [ -z "$zh_pkgs" ]; then
    skip "Пакеты с китайским переводом не найдены"
  else
    for p in $zh_pkgs; do
      pkg_remove "$p"
      ok "Удалён: $p"
    done
  fi
}

# ---------------------------------------------------------------------------
# 4. VPN-политика GL.iNet
# ---------------------------------------------------------------------------

disable_gl_vpn_policy_routing() {
  section "Отключение принудительной маршрутизации VPN от GL.iNet"
  if ! uci show route_policy >/dev/null 2>&1; then
    skip "Конфигурация route_policy (штатный VPN-клиент GL.iNet) не найдена — не требуется"
    return
  fi
  cur=$(uci get route_policy.global.enabled 2>/dev/null)
  if [ "$cur" = "0" ]; then
    skip "route_policy уже отключена (enabled=0)"
    return
  fi
  info "Отключает автоматические правила маршрутизации от штатного VPN-клиента GL.iNet,"
  info "чтобы они не конфликтовали с правилами forkop / другого VPN-клиента."
  ask_yn "Отключить route_policy от GL.iNet?" y || { skip "По выбору пользователя"; return; }
  uci set route_policy.global.enabled='0'
  uci commit route_policy
  /etc/init.d/vpn-client restart >> "$LOG" 2>&1
  ok "route_policy отключена, vpn-client перезапущен"
}

# ---------------------------------------------------------------------------
# 5. forkop
# ---------------------------------------------------------------------------

install_forkop() {
  section "Установка forkop (VPN/прокси-менеджер, форк Podkop)"
  if uci show podkop >/dev/null 2>&1 || uci show forkop >/dev/null 2>&1; then
    skip "forkop/podkop уже установлен"
    ask_yn "Запустить установщик повторно (обновление)?" n || return
  fi
  info "Официальный установщик: https://github.com/ushan0v/forkop"
  tmp="/tmp/forkop_install.sh"
  if fetch_to_file "https://raw.githubusercontent.com/ushan0v/forkop/main/install.sh" "$tmp" 20; then
    sh "$tmp" >> "$LOG" 2>&1
    rc=$?
    rm -f "$tmp"
    if [ $rc -eq 0 ]; then ok "forkop установлен"
    else err "Установщик forkop завершился с ошибкой (код $rc). Подробности: $LOG"
    fi
  else
    err "Не удалось скачать установщик forkop"
  fi
}

# ---------------------------------------------------------------------------
# 6. Отдельная сеть для VPN (forkop)
# ---------------------------------------------------------------------------

setup_vpn_interface() {
  section "Отдельная сеть для VPN (интерфейс vpnnet, 192.168.20.0/24)"
  if uci get network.vpnnet >/dev/null 2>&1; then
    skip "Интерфейс vpnnet уже настроен"
    return
  fi
  info "Создаст отдельный интерфейс vpnnet (br-vpnnet) со своим DHCP, DNS и"
  info "правилами файрвола — Wi-Fi/VPN можно привязать именно к этой сети,"
  info "не трогая основную LAN. Существующая сеть LAN не изменяется."
  ask_yn "Создать интерфейс vpnnet сейчас?" y || { skip "По выбору пользователя"; return; }

  uci set network.dev_vpnnet='device'
  uci set network.dev_vpnnet.type='bridge'
  uci set network.dev_vpnnet.name='br-vpnnet'

  uci set network.vpnnet='interface'
  uci set network.vpnnet.device='br-vpnnet'
  uci set network.vpnnet.proto='static'
  uci set network.vpnnet.ipaddr='192.168.20.1'
  uci set network.vpnnet.netmask='255.255.255.0'
  uci commit network

  uci set dhcp.vpnnet='dhcp'
  uci set dhcp.vpnnet.interface='vpnnet'
  uci set dhcp.vpnnet.start='100'
  uci set dhcp.vpnnet.limit='150'
  uci set dhcp.vpnnet.leasetime='12h'
  uci set dhcp.vpnnet.dhcpv4='server'
  uci commit dhcp

  uci set firewall.vpnnet='zone'
  uci set firewall.vpnnet.name='vpnnet'
  uci add_list firewall.vpnnet.network='vpnnet'
  uci set firewall.vpnnet.input='ACCEPT'
  uci set firewall.vpnnet.output='ACCEPT'
  uci set firewall.vpnnet.forward='REJECT'
  uci set firewall.vpnnet.masq='1'
  uci set firewall.vpnnet.mtu_fix='1'

  uci set firewall.vpnnet_wan='forwarding'
  uci set firewall.vpnnet_wan.src='vpnnet'
  uci set firewall.vpnnet_wan.dest='wan'

  uci set firewall.vpnnet_dns='rule'
  uci set firewall.vpnnet_dns.name='Allow-vpnnet-DNS'
  uci set firewall.vpnnet_dns.src='vpnnet'
  uci set firewall.vpnnet_dns.dest_port='53'
  uci set firewall.vpnnet_dns.proto='tcp udp'
  uci set firewall.vpnnet_dns.target='ACCEPT'

  uci set firewall.vpnnet_dhcp='rule'
  uci set firewall.vpnnet_dhcp.name='Allow-vpnnet-DHCP'
  uci set firewall.vpnnet_dhcp.src='vpnnet'
  uci set firewall.vpnnet_dhcp.dest_port='67-68'
  uci set firewall.vpnnet_dhcp.proto='udp'
  uci set firewall.vpnnet_dhcp.target='ACCEPT'
  uci commit firewall

  /etc/init.d/network reload  >> "$LOG" 2>&1
  /etc/init.d/dnsmasq reload  >> "$LOG" 2>&1
  /etc/init.d/firewall reload >> "$LOG" 2>&1

  if uci get network.vpnnet >/dev/null 2>&1; then
    ok "Интерфейс vpnnet создан (192.168.20.0/24)"
    info "Осталось вручную: создать/назначить Wi-Fi сеть на vpnnet в LuCI, и в"
    info "настройках forkop указать vpnnet как управляемый интерфейс."
  else
    err "Не удалось создать интерфейс vpnnet, проверьте лог: $LOG"
  fi
}

# ---------------------------------------------------------------------------
# 7. MiniUPnP
# ---------------------------------------------------------------------------

install_miniupnpd() {
  section "MiniUPnP (автооткрытие портов: торренты, игры)"
  pkg_install "miniupnpd-nftables" "miniupnpd (nftables)"
  pkg_installed "miniupnpd-nftables" || return 1

  uci set upnpd.config.enabled='1'
  uci set upnpd.config.enable_upnp='1'
  uci set upnpd.config.enable_natpmp='1'
  uci set upnpd.config.secure_mode='1'
  uci set upnpd.config.external_iface='wan'
  uci -q delete upnpd.config.internal_iface
  uci add_list upnpd.config.internal_iface='lan'
  vpn_added="нет"
  if uci get network.vpnnet >/dev/null 2>&1; then
    uci add_list upnpd.config.internal_iface='vpnnet'
    vpn_added="да"
  fi
  uci set upnpd.config.log_output='1'
  uci commit upnpd

  /etc/init.d/miniupnpd enable  >> "$LOG" 2>&1
  /etc/init.d/miniupnpd restart >> "$LOG" 2>&1

  if /etc/init.d/miniupnpd enabled 2>/dev/null; then
    ok "MiniUPnP включён для lan (vpnnet добавлен: $vpn_added)"
  else
    warn "MiniUPnP установлен, но служба не подтвердила запуск — проверьте вручную"
  fi
}

# ---------------------------------------------------------------------------
# 8. zram
# ---------------------------------------------------------------------------

install_zram() {
  section "zram (сжатый swap в ОЗУ)"
  if [ -f /etc/init.d/zram ] && /etc/init.d/zram enabled 2>/dev/null; then
    skip "zram уже установлен и включён"
    return
  fi
  pkg_install "zram-swap" "zram-swap"

  mem_kb=$(awk '/MemTotal/{print $2}' /proc/meminfo)
  mem_mb=$((mem_kb / 1024))
  if   [ "$mem_mb" -le 256 ]; then zram_mb=128
  elif [ "$mem_mb" -le 512 ]; then zram_mb=256
  elif [ "$mem_mb" -le 1024 ]; then zram_mb=512
  else zram_mb=$((mem_mb / 2))
  fi
  info "ОЗУ: ${mem_mb}MB → размер zram: ${zram_mb}MB"

  uci set system.@system[0].zram_size_mb="$zram_mb" 2>>"$LOG"
  uci commit system
  /etc/init.d/zram enable >> "$LOG" 2>&1
  /etc/init.d/zram start  >> "$LOG" 2>&1 || /etc/init.d/zram restart >> "$LOG" 2>&1

  if /etc/init.d/zram enabled 2>/dev/null; then
    ok "zram включён (${zram_mb}MB)"
  else
    warn "zram установлен, но не удалось подтвердить, что служба включена"
  fi
}

# ---------------------------------------------------------------------------
# 9. Тема Footstrap
# ---------------------------------------------------------------------------

install_footstrap_theme() {
  section "Тема оформления LuCI: Footstrap"
  if pkg_installed "luci-theme-footstrap"; then
    skip "Тема footstrap уже установлена"
  else
    tmp="/tmp/footstrap_install.sh"
    if fetch_to_file "https://raw.githubusercontent.com/VizzleTF/luci-theme-footstrap/main/install.sh" "$tmp" 20; then
      sh "$tmp" >> "$LOG" 2>&1
      rc=$?
      rm -f "$tmp"
      if [ $rc -eq 0 ] && pkg_installed "luci-theme-footstrap"; then
        ok "Тема footstrap установлена"
      else
        err "Не удалось установить тему footstrap (код $rc)"; return 1
      fi
    else
      err "Не удалось скачать установщик темы footstrap"; return 1
    fi
  fi

  if ask_yn "Сделать Footstrap активной темой LuCI?" y; then
    uci set luci.main.mediaurlbase='/luci-static/footstrap' 2>>"$LOG"
    uci commit luci
    ok "Тема footstrap назначена активной"
  fi
}

# ---------------------------------------------------------------------------
# 10. CPU governor
# ---------------------------------------------------------------------------

set_cpu_performance_governor() {
  section "CPU governor: performance"
  if [ ! -f /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor ]; then
    skip "cpufreq недоступен на этой системе — пункт не применим"
    return
  fi
  avail=$(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_available_governors 2>/dev/null)
  if ! echo "$avail" | grep -qw performance; then
    warn "Governor 'performance' недоступен на этом устройстве (доступны: $avail)"
    return
  fi
  cur=$(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor 2>/dev/null)
  if [ "$cur" = "performance" ] && [ -f /etc/rc.local ] && grep -q "scaling_governor" /etc/rc.local; then
    skip "Governor уже performance и сохранён в автозагрузке"
    return
  fi

  info "Governor 'performance' держит частоту CPU постоянно максимальной."
  info "Плюс: стабильно низкие задержки/джиттер под нагрузкой (VPN, NAT, Wi-Fi)."
  info "Минус: немного больше энергопотребления/тепла (для роутера обычно не критично)."
  ask_yn "Установить governor 'performance' (сейчас и в автозагрузке)?" y || { skip "По выбору пользователя"; return; }

  echo performance | tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor > /dev/null 2>>"$LOG"

  if [ -f /etc/rc.local ]; then
    grep -q "scaling_governor" /etc/rc.local || \
      sed -i '/exit 0/i echo performance | tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor > /dev/null' /etc/rc.local
  fi

  cur=$(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor 2>/dev/null)
  if [ "$cur" = "performance" ]; then
    ok "Governor установлен: performance (сохранено в /etc/rc.local)"
  else
    err "Не удалось применить governor performance"
  fi
}

# ---------------------------------------------------------------------------
# 11. Сетевые твики (джиттер)
# ---------------------------------------------------------------------------

apply_network_tweaks() {
  section "Твики сети для снижения джиттера"
  info "tcp_fastopen=3 — ускоряет установку TCP-соединений (данные в SYN)"
  info "tcp_slow_start_after_idle=0 — не сбрасывает окно перегрузки на простаивавших соединениях"
  info "somaxconn / netdev_max_backlog / tcp_max_syn_backlog — увеличивают очереди,"
  info "  снижая потери пакетов при всплесках нагрузки (много соединений одновременно)"
  info "Эффект заметнее на роутерах с большим числом клиентов; на Flint 2 с малой"
  info "нагрузкой изменения обычно небольшие, но безвредные."
  if ask_yn "Применить сетевые sysctl-твики?" n; then
    conf="/etc/sysctl.d/99-jitter-tweaks.conf"
    mkdir -p /etc/sysctl.d
    cat > "$conf" <<'EOF'
net.ipv4.tcp_fastopen=3
net.ipv4.tcp_slow_start_after_idle=0
net.core.somaxconn=4096
net.core.netdev_max_backlog=16384
net.ipv4.tcp_max_syn_backlog=8192
EOF
    sysctl -p "$conf" >> "$LOG" 2>&1
    ok "sysctl-твики применены и сохранены в $conf"
  else
    skip "По выбору пользователя"
  fi

  section "AQL / Wi-Fi (mac80211) твики очередей"
  if [ ! -d /sys/kernel/debug/ieee80211 ]; then
    mount | grep -q debugfs || mount -t debugfs none /sys/kernel/debug >> "$LOG" 2>&1
  fi
  phys=$(ls /sys/kernel/debug/ieee80211 2>/dev/null)
  if [ -z "$phys" ]; then
    skip "debugfs mac80211 недоступен на этом устройстве — AQL-твики пропущены"
    return
  fi
  info "AQL (Airtime Queue Limit) регулирует буферизацию пакетов на Wi-Fi:"
  info "меньшие лимиты = ниже задержка/джиттер, но риск потери пропускной способности"
  info "на дальних/слабых клиентах. Полезно для игр/звонков, менее важно для файлов."
  ask_yn "Применить AQL-твики для радиомодулей Wi-Fi ($phys)?" n || { skip "По выбору пользователя"; return; }

  aql_l=1500; aql_h=5000; aql_thr=12000; fq_limit=1200
  applied=0
  for phy in $phys; do
    dbg="/sys/kernel/debug/ieee80211/$phy"
    [ -f "$dbg/aql_txq_limit" ] || continue
    for ac in 0 1 2 3; do
      echo "$ac $aql_l $aql_h" > "$dbg/aql_txq_limit" 2>>"$LOG"
    done
    echo "$aql_thr" > "$dbg/aql_threshold" 2>>"$LOG"
    [ -f "$dbg/aqm" ] && echo "fq_limit $fq_limit" > "$dbg/aqm" 2>>"$LOG"
    applied=1
    ok "AQL применён для $phy"
  done
  if [ "$applied" = "0" ]; then
    warn "Ни один радиомодуль не поддерживает AQL debugfs — пропущено"
    return
  fi

  if [ -f /etc/rc.local ] && ! grep -q "AQL Tweaks (router-setup.sh)" /etc/rc.local; then
    tmpf="/tmp/rc.local.aql"
    awk -v l="$aql_l" -v h="$aql_h" -v thr="$aql_thr" -v fq="$fq_limit" '
      /exit 0/ && !done {
        print "# AQL Tweaks (router-setup.sh)"
        print "for p in $(ls /sys/kernel/debug/ieee80211 2>/dev/null); do"
        print "  d=\"/sys/kernel/debug/ieee80211/$p\""
        print "  [ -f \"$d/aql_txq_limit\" ] || continue"
        print "  for ac in 0 1 2 3; do echo \"$ac " l " " h "\" > \"$d/aql_txq_limit\"; done"
        print "  echo " thr " > \"$d/aql_threshold\""
        print "  [ -f \"$d/aqm\" ] && echo \"fq_limit " fq "\" > \"$d/aqm\""
        print "done"
        done=1
      }
      { print }
    ' /etc/rc.local > "$tmpf" && mv "$tmpf" /etc/rc.local
    ok "AQL-твики сохранены в автозагрузку (/etc/rc.local)"
  fi
}

# ---------------------------------------------------------------------------
# 12. Полезные пакеты
# ---------------------------------------------------------------------------

install_useful_packages() {
  section "Полезные пакеты"
  pkg_install "openssh-sftp-server" "SFTP-сервер (SSH)"
  pkg_install "unzip" "unzip"
  pkg_install "nano-full" "nano (полная версия)"
  pkg_install "lm-sensors" "lm-sensors"
  pkg_install "ethtool" "ethtool"
  pkg_install "iperf3" "iperf3"
  pkg_install "htop" "htop"

  if pkg_installed "luci-app-temp-status"; then
    skip "luci-app-temp-status уже установлен"
  else
    info "Установка luci-app-temp-status из github.com/gSpotx2f/luci-app-temp-status"
    api_json=$(fetch_to_stdout "https://api.github.com/repos/gSpotx2f/luci-app-temp-status/releases/latest" 15 | tr -d '\n')
    ext="ipk"; [ "$PKG" = "apk" ] && ext="apk"
    url=$(echo "$api_json" | grep -o "\"browser_download_url\":\"[^\"]*luci-app-temp-status[^\"]*\.${ext}\"" | head -n1 | sed 's/.*:"//;s/"$//')
    if [ -z "$url" ]; then
      warn "Не найден релиз luci-app-temp-status для $PKG — пропуск (можно поставить вручную)"
    else
      dl="/tmp/luci-app-temp-status.$ext"
      if fetch_to_file "$url" "$dl" 20; then
        if [ "$PKG" = "apk" ]; then apk add --allow-untrusted "$dl" >> "$LOG" 2>&1
        else opkg install "$dl" >> "$LOG" 2>&1
        fi
        rm -f "$dl"
        pkg_installed "luci-app-temp-status" && ok "luci-app-temp-status установлен" || err "Не удалось установить luci-app-temp-status"
      else
        warn "Не удалось скачать luci-app-temp-status"
      fi
    fi
  fi
}

# ---------------------------------------------------------------------------
# 13. Часовой пояс
# ---------------------------------------------------------------------------

set_timezone() {
  section "Часовой пояс"
  cur_zone=$(uci get system.@system[0].zonename 2>/dev/null)
  if [ -n "$cur_zone" ]; then
    info "Текущий часовой пояс: $cur_zone"
    ask_yn "Изменить часовой пояс?" n || { skip "Оставлен текущий: $cur_zone"; return; }
  fi

  city=$(ask_val "Введите ваш город (лучше на английском, напр. Moscow)" "")
  [ -z "$city" ] && { warn "Город не указан — пропуск"; return; }

  q=$(echo "$city" | sed 's/ /%20/g')
  json=$(fetch_to_stdout "https://geocoding-api.open-meteo.com/v1/search?name=${q}&count=1&language=ru&format=json" 15 | tr -d '\n')

  tz=$(echo "$json" | sed -n 's/.*"timezone":"\([^"]*\)".*/\1/p' | head -n1)
  found_name=$(echo "$json" | sed -n 's/.*"name":"\([^"]*\)".*/\1/p' | head -n1)
  found_country=$(echo "$json" | sed -n 's/.*"country":"\([^"]*\)".*/\1/p' | head -n1)

  if [ -z "$tz" ]; then
    err "Город '$city' не найден или сервис геокодирования недоступен — часовой пояс не изменён"
    return 1
  fi

  info "Найдено: ${found_name:-$city}${found_country:+, $found_country} — часовой пояс: $tz"
  ask_yn "Применить этот часовой пояс?" y || { skip "По выбору пользователя"; return; }

  pkg_install "zoneinfo-core" "zoneinfo (данные часовых поясов)"
  if [ ! -e "/usr/share/zoneinfo/$tz" ]; then
    warn "Зона /usr/share/zoneinfo/$tz не найдена в zoneinfo-core, пробуем zoneinfo-full..."
    pkg_install "zoneinfo-full" "zoneinfo-full"
  fi

  uci set system.@system[0].zonename="$tz"
  uci set system.@system[0].timezone="$tz"
  uci commit system
  echo "$tz" > /etc/TZ 2>>"$LOG"
  export TZ="$tz"
  /etc/init.d/system reload >> "$LOG" 2>&1 || /etc/init.d/system restart >> "$LOG" 2>&1

  ok "Часовой пояс установлен: $tz (текущее время: $(date))"
}

# ---------------------------------------------------------------------------
# 14. Итоговая проверка
# ---------------------------------------------------------------------------

final_verification() {
  section "Итоговая проверка"

  check_line() {
    label="$1"; cond="$2"
    if eval "$cond"; then ok "$label"; else warn "$label — не подтверждено"; fi
  }

  check_line "Пакетный менеджер работает" "command -v $PKG >/dev/null 2>&1"
  [ "$IS_GLINET" = "yes" ] && check_line "Русский язык GL.iNet" "[ -f /www/i18n/release.ru.json ]"
  check_line "Русский язык LuCI"    "pkg_installed luci-i18n-base-ru"
  check_line "zram активен"         "/etc/init.d/zram enabled 2>/dev/null"
  check_line "Тема footstrap"       "pkg_installed luci-theme-footstrap"
  check_line "forkop установлен"    "uci show podkop >/dev/null 2>&1 || uci show forkop >/dev/null 2>&1"
  check_line "Интерфейс vpnnet"     "uci get network.vpnnet >/dev/null 2>&1"
  check_line "MiniUPnP запущен"     "/etc/init.d/miniupnpd enabled 2>/dev/null"
  check_line "htop установлен"      "pkg_installed htop"

  printf '\n'
  info "Полный лог выполнения: $LOG"
  info "Если что-то не сработало:"
  info " 1) Проверьте интернет на роутере: ping -c3 openwrt.org"
  info " 2) Посмотрите ошибки/предупреждения: grep -E '\\[ERR\\]|\\[WARN\\]' $LOG"
  info " 3) Повторный запуск скрипта безопасен — готовые шаги будут пропущены"
  info " 4) Проверить репозитории вручную: cat /etc/opkg/customfeeds.conf (opkg) или cat /etc/apk/repositories (apk)"
}

# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

main() {
  check_root
  check_prereqs
  banner
  detect_system
  check_internet

  install_stock_openwrt_repos
  install_immortalwrt_repo
  pkg_update_once

  install_gl_russian_lang
  install_system_ru_language

  disable_gl_vpn_policy_routing
  install_forkop
  setup_vpn_interface
  install_miniupnpd

  install_zram
  install_footstrap_theme
  set_cpu_performance_governor
  apply_network_tweaks

  install_useful_packages
  set_timezone

  final_verification

  printf '\n%b Готово! %b\n' "$C_GREEN$C_BOLD" "$C_RESET"
}

main "$@"
