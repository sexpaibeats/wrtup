#!/bin/sh
# ==============================================================================
# Поддержка OpenWrt 24 / 25+ / прошивки от GL.iNet (4.5+)
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

# Запрос на сетевые твики
printf "${C}[?]${W} Применить ли сетевые твики (Sysctl TCP, Wi-Fi AQL)? (y/N)

Подробнее о твиках:
Твики ядра и TCP (Sysctl):
 ⁠net.ipv4.tcp_fastopen=3⁠ — включает TCP Fast Open. Позволяет отправлять данные уже в самом первом пакете (SYN) при установке соединения. Ускоряет открытие страниц, снижает задержки (полезно при работе с прокси/VLESS).
 ⁠net.ipv4.tcp_slow_start_after_idle=0⁠ — отключает «медленный старт» после простоя. Соединение не будет заново плавно разгоняться, а сразу продолжит на максимальной скорости.
 ⁠net.core.somaxconn=4096⁠ и ⁠net.ipv4.tcp_max_syn_backlog=8192⁠ — увеличивают лимит полуоткрытых соединений и очередь прослушивания. Защищают роутер от захлебывания при агрессивном скачивании торрентов с тысячами пиров или при DDoS-подобной нагрузке.
 ⁠net.core.netdev_max_backlog=16384⁠ — увеличивает буфер пакетов сетевой карты. Идеально для 2.5G портов, чтобы пакеты не терялись при пиковых всплесках трафика. На роутерах с 1 ГБ ОЗУ (Flint 2) выделение памяти под этот буфер вообще незаметно.
Твики Wi-Fi (AQL — Airtime Queue Limits):
 Это продвинутый механизм борьбы с Bufferbloat (раздуванием буфера) на беспроводном интерфейсе.
 Если кто-то начинает скачивать тяжелый файл по Wi-Fi, радиоэфир забивается. Без AQL пинг в играх у других устройств по Wi-Fi может повышаться до 100–300 мс.
 ⁠aql_txq_limit⁠, ⁠fq_limit⁠ — аппаратно включают алгоритм Fair Queuing (честная очередь) на уровне радиодрайвера ⁠mac80211⁠. Пинг остается стабильным даже при забитом эфире. : "
read APPLY_TWEAKS

echo "----------------------------------------------------"

# 2. Обновление пакетов
info "Обновление стоковых репозиториев..."
$PM_UPD >/dev/null 2>&1 || { err "Ошибка обновления пакетов. Проверьте интернет!"; exit 1; }
ok "Репозитории обновлены."

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
    info "Роутер не от GL.iNet, пропуск."
fi

# 4. Базовые утилиты
info "Установка базовых пакетов (SFTP, nano, htop...)"
$PM_INS openssh-sftp-server unzip nano-full lm-sensors ethtool iperf3 htop >/dev/null 2>&1
ok "Базовые утилиты установлены."

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
info "Установка/Проверка Forkop..."
if command -v forkop >/dev/null 2>&1; then
    ok "Forkop уже установлен."
else
    sh -c "$(curl -sL https://raw.githubusercontent.com/ushan0v/forkop/main/install.sh)" >/dev/null 2>&1 || true
    ok "Установщик Forkop отработал."
fi

# 7. Тема Footstrap
info "Установка темы Footstrap..."
if uci get luci.themes.Footstrap >/dev/null 2>&1; then
    ok "Тема Footstrap уже установлена."
else
    sh -c "$(curl -sL https://raw.githubusercontent.com/VizzleTF/luci-theme-footstrap/main/install.sh)" >/dev/null 2>&1 || true
    uci set luci.main.mediaurlbase='/luci-static/footstrap'
    uci commit luci
    ok "Тема применена."
fi

# 8. Модуль температур
info "Установка luci-app-temp-status..."
if uci get luci.temp-status >/dev/null 2>&1 || ls /usr/share/luci/menu.d/luci-app-temp-status* >/dev/null 2>&1; then
    ok "Модуль температур установлен."
else
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
    ok "Governor уже настроен."
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
info "Создание интерфейса br-vpnnet (192.168.20.0/24)..."
if ! uci get network.vpnnet >/dev/null 2>&1; then
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
    warn "Интерфейс vpnnet уже существует."
fi

# 12. MiniUPnP
info "Настройка MiniUPnP (проброс портов)..."
if [ "$PM" = "apk" ]; then $PM_INS miniupnpd-nftables >/dev/null 2>&1; else $PM_INS miniupnpd >/dev/null 2>&1; fi

if uci get upnpd.config >/dev/null 2>&1; then
    uci set upnpd.config.enabled='1'
    uci set upnpd.config.enable_upnp='1'
    uci set upnpd.config.enable_natpmp='1'
    uci set upnpd.config.secure_mode='1'
    uci set upnpd.config.external_iface='wan'
    
    uci delete upnpd.config.internal_iface 2>/dev/null || true
    uci add_list upnpd.config.internal_iface='lan'
    uci add_list upnpd.config.internal_iface='vpnnet'
    
    uci set upnpd.config.log_output='1'
    uci commit upnpd
    /etc/init.d/miniupnpd enable 2>/dev/null || true
    /etc/init.d/miniupnpd restart 2>/dev/null || true
    ok "UPnP активирован (lan + vpnnet)."
else
    err "Не найден конфиг UPnP."
fi

echo -e "${C}====================================================${W}"
echo -e "${G} УСТАНОВКА УСПЕШНО ЗАВЕРШЕНА!${W}"
echo -e " Рекомендуется выполнить полную перезагрузку:"
echo -e " ${Y}reboot${W}"
echo -e "${C}====================================================${W}"
