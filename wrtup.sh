#!/bin/sh
# ==============================================================================
# Поддержка OpenWrt/Immortalwrt (24 / 25+) / прошивки GL.iNet (4.5+)
# Пакетные менеджеры: opkg / apk
# ==============================================================================

G="\033[32m"
Y="\033[33m"
R="\033[31m"
C="\033[36m"
W="\033[0m"

info() { echo -e "${C}[INFO]${W} $1"; }
ok() { echo -e "${G}[OK]${W} $1"; }
warn() { echo -e "${Y}[WARN]${W} $1"; }
err() { echo -e "${R}[ERROR]${W} $1"; }

echo -e "${C}====================================================${W}"
echo -e "${G}   Начало первичной настройки роутера...${W}"
echo -e "${C}====================================================${W}"

# 1. Определение платформы
MODEL=$(cat /tmp/sysinfo/model 2>/dev/null || cat /proc/device-tree/model 2>/dev/null || echo "Unknown Router")
OS_VER=$(grep -oP 'DISTRIB_DESCRIPTION="\K[^"]+' /etc/openwrt_release 2>/dev/null || echo "OpenWrt")
TOTAL_RAM=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)

if command -v apk >/dev/null 2>&1; then
    PM="apk"
    PM_UPD="apk update"
    PM_INS="apk add --no-cache"
    EXT="apk"
else
    PM="opkg"
    PM_UPD="opkg update"
    PM_INS="opkg install"
    EXT="ipk"
fi

IS_GLINET=0
grep -iq "gl.inet" /etc/openwrt_release && IS_GLINET=1

info "Устройство: $MODEL"
info "Система: $OS_VER | Менеджер: $PM"
info "ОЗУ: ${TOTAL_RAM} MB"

# Запрос на сетевые твики (фикс чтения из TTY для pipe-установки)
printf "${C}[?]${W} Применить ли сетевые твики (Sysctl TCP, Wi-Fi AQL)? (y/N)

Подробнее о твиках:
• Sysctl (TCP): Ускоряет установку соединений (TCP Fast Open), убирает "медленный старт" после пауз, увеличивает буферы сетевой карты (для 2.5G портов) и лимиты подключений для торрентов/DDoS.
• AQL (Wi-Fi): Аппаратно включает "честную очередь" на уровне радиочипа. Предотвращает скачки пинга в играх (Bufferbloat), когда кто-то другой забивает Wi-Fi скачиванием тяжелых файлов. : "
read APPLY_TWEAKS < /dev/tty

echo "----------------------------------------------------"

# 2. Добавление официальных репозиториев (OpenWrt / ImmortalWrt)
info "Добавление стоковых репозиториев..."
if [ -f /etc/openwrt_release ]; then
    . /etc/openwrt_release
    
    if echo "$DISTRIB_DESCRIPTION" | grep -iq "immortalwrt"; then
        REPO_BASE="https://mirrors.vsean.net/openwrt/releases/${DISTRIB_RELEASE}"
        IS_IMMO=1
    else
        REPO_BASE="https://downloads.openwrt.org/releases/${DISTRIB_RELEASE}"
        IS_IMMO=0
    fi

    if [ "$PM" = "apk" ]; then
        REPO_FILE="/etc/apk/repositories.d/custom_feeds.list"
        mkdir -p /etc/apk/repositories.d
        cat <<EOF > "$REPO_FILE"
$REPO_BASE/targets/$DISTRIB_TARGET/packages
$REPO_BASE/packages/$DISTRIB_ARCH/base
$REPO_BASE/packages/$DISTRIB_ARCH/luci
$REPO_BASE/packages/$DISTRIB_ARCH/packages
$REPO_BASE/packages/$DISTRIB_ARCH/routing
$REPO_BASE/packages/$DISTRIB_ARCH/telephony
EOF
        [ "$IS_IMMO" -eq 0 ] && echo "$REPO_BASE/packages/$DISTRIB_ARCH/video" >> "$REPO_FILE"
    else
        REPO_FILE="/etc/opkg/customfeeds.conf"
        cat <<EOF > "$REPO_FILE"
src/gz custom_core $REPO_BASE/targets/$DISTRIB_TARGET/packages
src/gz custom_base $REPO_BASE/packages/$DISTRIB_ARCH/base
src/gz custom_luci $REPO_BASE/packages/$DISTRIB_ARCH/luci
src/gz custom_packages $REPO_BASE/packages/$DISTRIB_ARCH/packages
src/gz custom_routing $REPO_BASE/packages/$DISTRIB_ARCH/routing
src/gz custom_telephony $REPO_BASE/packages/$DISTRIB_ARCH/telephony
EOF
        [ "$IS_IMMO" -eq 0 ] && echo "src/gz custom_video $REPO_BASE/packages/$DISTRIB_ARCH/video" >> "$REPO_FILE"
    fi
    ok "Сгенерированы репозитории для $DISTRIB_RELEASE ($DISTRIB_TARGET)."
fi

info "Обновление списков пакетов..."
$PM_UPD >/dev/null 2>&1 || { err "Ошибка обновления пакетов. Проверьте интернет!"; exit 1; }
ok "Списки пакетов обновлены."

# 3. Интеграция с GL.iNet
if [ "$IS_GLINET" -eq 1 ]; then
    info "Применение специфичных фиксов для GL.iNet..."
    if uci get route_policy.global.enabled >/dev/null 2>&1; then
        uci set route_policy.global.enabled='0'
        uci commit route_policy
        /etc/init.d/vpn-client restart 2>/dev/null || true
        ok "Служба route_policy отключена (фикс обхода блокировок)."
    fi

    if ! uci get luci.languages.ru >/dev/null 2>&1; then
        info "Установка русского языка админки GL.iNet..."
        LANG_URL=$(curl -s "https://api.github.com/repos/gl-inet/router-sdk-languages/releases/latest" | grep "browser_download_url.*$EXT" | grep "ru" | cut -d '"' -f 4 | head -n 1)
        if [ -n "$LANG_URL" ]; then
            curl -sL "$LANG_URL" -o "/tmp/lang_ru.$EXT"
            if [ "$PM" = "apk" ]; then apk add --allow-untrusted "/tmp/lang_ru.apk" >/dev/null 2>&1; else opkg install "/tmp/lang_ru.ipk" >/dev/null 2>&1; fi
            rm -f "/tmp/lang_ru.$EXT"
            ok "Русский язык установлен."
        fi
    fi
else
    info "Роутер не от GL.iNet, пропуск фиксов производителя."
fi

# 4. Базовые утилиты (с индивидуальной проверкой)
info "Установка базовых утилит..."
PACKAGES="openssh-sftp-server unzip nano-full lm-sensors ethtool iperf3 htop"

for pkg in $PACKAGES; do
    if [ "$PM" = "apk" ]; then
        if apk info -e $pkg >/dev/null 2>&1; then
            ok "$pkg уже установлен."
        else
            info "Установка $pkg..."
            $PM_INS $pkg >/dev/null 2>&1 && ok "$pkg установлен." || err "Ошибка установки $pkg."
        fi
    else
        if opkg status $pkg 2>/dev/null | grep -q "Status: install ok installed"; then
            ok "$pkg уже установлен."
        else
            info "Установка $pkg..."
            $PM_INS $pkg >/dev/null 2>&1 && ok "$pkg установлен." || err "Ошибка установки $pkg."
        fi
    fi
done

# 5. zRAM
info "Настройка zRAM..."
if ! command -v zramctl >/dev/null 2>&1 && ! ls /dev/zram* >/dev/null 2>&1; then
    $PM_INS zram-swap >/dev/null 2>&1
fi

ZRAM_MB=$((TOTAL_RAM / 2))
[ "$ZRAM_MB" -gt 512 ] && ZRAM_MB=512
[ "$ZRAM_MB" -lt 128 ] && ZRAM_MB=128

if uci get system.@system[0] >/dev/null 2>&1; then
    uci set system.@system[0].zram_size_mb="$ZRAM_MB"
    uci commit system
    /etc/init.d/zram enable 2>/dev/null || true
    /etc/init.d/zram start 2>/dev/null || true
    ok "zRAM активирован (${ZRAM_MB} MB)."
fi

# 6. Установка Forkop
info "Проверка Forkop..."
if command -v forkop >/dev/null 2>&1; then
    ok "Forkop уже установлен."
else
    info "Установка Forkop..."
    sh -c "$(curl -sL https://raw.githubusercontent.com/ushan0v/forkop/main/install.sh)" >/dev/null 2>&1 || true
    ok "Установщик Forkop отработал."
fi

# 7. Тема Footstrap
info "Проверка темы Footstrap..."
if uci get luci.themes.Footstrap >/dev/null 2>&1; then
    ok "Тема Footstrap уже установлена."
else
    info "Установка темы Footstrap..."
    sh -c "$(curl -sL https://raw.githubusercontent.com/VizzleTF/luci-theme-footstrap/main/install.sh)" >/dev/null 2>&1 || true
    uci set luci.main.mediaurlbase='/luci-static/footstrap'
    uci commit luci
    ok "Тема применена."
fi

# 8. Модуль температур
info "Проверка luci-app-temp-status..."
if uci get luci.temp-status >/dev/null 2>&1 || ls /usr/share/luci/menu.d/luci-app-temp-status* >/dev/null 2>&1; then
    ok "Модуль температур уже установлен."
else
    info "Установка luci-app-temp-status..."
    if [ "$PM" = "apk" ]; then
        curl -sL "https://github.com/gSpotx2f/packages-openwrt/raw/master/25.12/luci-app-temp-status-0.8.1-r1.apk" -o "/tmp/temp.apk"
        apk add --allow-untrusted "/tmp/temp.apk" >/dev/null 2>&1
    else
        curl -sL "https://github.com/gSpotx2f/packages-openwrt/raw/master/24.10/luci-app-temp-status_0.8.1-r1_all.ipk" -o "/tmp/temp.ipk"
        opkg install "/tmp/temp.ipk" >/dev/null 2>&1
    fi
    rm -f /tmp/temp.*
    /etc/init.d/rpcd restart 2>/dev/null || true
    ok "Модуль температур добавлен."
fi

# 9. CPU Governor
info "Настройка CPU Performance..."
echo performance | tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor > /dev/null 2>&1
if ! grep -q "scaling_governor" /etc/rc.local; then
    sed -i '/exit 0/i echo performance | tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor > /dev/null 2>&1' /etc/rc.local
    ok "Governor 'performance' применен."
else
    ok "Governor 'performance' уже настроен."
fi

# 10. Сетевые твики (Sysctl + AQL)
if [ "$APPLY_TWEAKS" = "y" ] || [ "$APPLY_TWEAKS" = "Y" ]; then
    info "Применение сетевых TCP-твиков (Sysctl)..."
    cat << 'EOF' > /etc/sysctl.d/99-network-tweaks.conf
net.ipv4.tcp_fastopen=3
net.ipv4.tcp_slow_start_after_idle=0
net.core.somaxconn=4096
net.core.netdev_max_backlog=16384
net.ipv4.tcp_max_syn_backlog=8192
EOF
    sysctl -p /etc/sysctl.d/99-network-tweaks.conf >/dev/null 2>&1
    ok "TCP-параметры обновлены."

    info "Применение Wi-Fi AQL Tweaks..."
    if ! grep -q "aql_txq_limit" /etc/rc.local; then
        sed -i '/exit 0/i \
# AQL Tweaks\
if [ -d "/sys/kernel/debug/ieee80211" ]; then\
    mount -t debugfs none /sys/kernel/debug 2>/dev/null || true\
    for wl in wl0 wl1; do\
        if [ -d "/sys/kernel/debug/ieee80211/$wl" ]; then\
            for ac in 0 1 2 3; do echo "$ac 1500 5000" > "/sys/kernel/debug/ieee80211/$wl/aql_txq_limit" 2>/dev/null; done\
            echo "12000" > "/sys/kernel/debug/ieee80211/$wl/aql_threshold" 2>/dev/null\
            echo "fq_limit 1200" > "/sys/kernel/debug/ieee80211/$wl/aqm" 2>/dev/null\
        fi\
    done\
fi' /etc/rc.local
        ok "AQL-твики добавлены в rc.local."
    else
        ok "AQL-твики уже прописаны."
    fi
else
    warn "Сетевые твики пропущены пользователем."
fi

# 11. Интерфейс VPN
info "Проверка интерфейса br-vpnnet (192.168.20.0/24)..."
if ! uci get network.vpnnet >/dev/null 2>&1; then
    info "Создание интерфейса br-vpnnet..."
    uci set network.vpnnet='interface'
    uci set network.vpnnet.proto='static'
    uci set network.vpnnet.device='br-vpnnet'
    uci set network.vpnnet.ipaddr='192.168.20.1'
    uci set network.vpnnet.netmask='255.255.255.0'
    uci commit network
    
    uci set dhcp.vpnnet='dhcp'
    uci set dhcp.vpnnet.interface='vpnnet'
    uci set dhcp.vpnnet.start='100'
    uci set dhcp.vpnnet.limit='150'
    uci set dhcp.vpnnet.leasetime='12h'
    uci commit dhcp

    uci add firewall zone >/dev/null
    uci set firewall.@zone[-1].name='vpnnet_zone'
    uci set firewall.@zone[-1].network='vpnnet'
    uci set firewall.@zone[-1].input='ACCEPT'
    uci set firewall.@zone[-1].output='ACCEPT'
    uci set firewall.@zone[-1].forward='ACCEPT'
    
    uci add firewall forwarding >/dev/null
    uci set firewall.@forwarding[-1].src='vpnnet_zone'
    uci set firewall.@forwarding[-1].dest='wan'
    uci commit firewall

    /etc/init.d/network restart >/dev/null 2>&1
    /etc/init.d/dnsmasq restart >/dev/null 2>&1
    /etc/init.d/firewall restart >/dev/null 2>&1
    ok "br-vpnnet и firewall-зоны созданы."
else
    ok "Интерфейс vpnnet уже существует."
fi

# 12. MiniUPnP
info "Настройка MiniUPnP (проброс портов)..."
UPNP_PKG="miniupnpd"
[ "$PM" = "apk" ] && UPNP_PKG="miniupnpd-nftables"

if command -v upnpd >/dev/null 2>&1 || ls /etc/init.d/miniupnpd >/dev/null 2>&1; then
    ok "Пакет $UPNP_PKG уже установлен."
else
    $PM_INS $UPNP_PKG >/dev/null 2>&1
    ok "Пакет $UPNP_PKG установлен."
fi

if uci get upnpd.config >/dev/null 2>&1; then
    uci set upnpd.config.enabled='1'
    uci set upnpd.config.enable_upnp='1'
    uci set upnpd.config.enable_natpmp='1'
    uci set upnpd.config.secure_mode='1'
    uci set upnpd.config.external_iface='wan'
    uci set upnpd.config.log_output='1'

    # Проверка, добавлены ли уже интерфейсы
    HAS_LAN=$(uci show upnpd | grep internal_iface | grep -c "'lan'")
    HAS_VPN=$(uci show upnpd | grep internal_iface | grep -c "'vpnnet'")

    if [ "$HAS_LAN" -eq 0 ] || [ "$HAS_VPN" -eq 0 ]; then
        uci delete upnpd.config.internal_iface 2>/dev/null || true
        uci add_list upnpd.config.internal_iface='lan'
        uci add_list upnpd.config.internal_iface='vpnnet'
        uci commit upnpd
        /etc/init.d/miniupnpd restart 2>/dev/null || true
        ok "MiniUPnP перенастроен (добавлен vpnnet)."
    else
        ok "MiniUPnP уже настроен для lan и vpnnet."
    fi
    /etc/init.d/miniupnpd enable 2>/dev/null || true
else
    err "Не найден конфиг UPnP."
fi

echo -e "${C}====================================================${W}"
echo -e "${G} УСТАНОВКА УСПЕШНО ЗАВЕРШЕНА!${W}"
echo -e " Рекомендуется выполнить полную перезагрузку:"
echo -e " ${Y}reboot${W}"
echo -e "${C}====================================================${W}"
