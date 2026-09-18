#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import io
import re
import socket
import time
import telebot
from telebot import types
from flask import Flask, request
from threading import Thread
from datetime import datetime

# ============ НАСТРОЙКИ ============
BOT_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")

print("[DEBUG] Токен: " + str(len(BOT_TOKEN)))


# ============ FLASK ============
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is running"

@app.route("/health")
def health():
    return "OK"

def run_web():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)


# ============ БОТ ============
bot = telebot.TeleBot(BOT_TOKEN) if BOT_TOKEN else None


# ============================================================
#                    ЗАЦЕПКИ
# ============================================================

def extract_years_from_nick(nick):
    """Ищет годы в нике."""
    years = []
    for m in re.findall(r"(19\d{2}|20\d{2})", nick):
        try:
            years.append(int(m))
        except Exception:
            pass
    return years


def extract_short_dates(nick):
    """Ищет короткие даты (02, 99, 03)."""
    result = []
    for m in re.findall(r"\b(\d{2})\b", nick):
        try:
            n = int(m)
            if 1 <= n <= 31:
                result.append(("день месяца?", n))
            elif 50 <= n <= 99:
                result.append(("год (19XX)?", 1900 + n))
        except Exception:
            pass
    return result


def normalize_leet(nick):
    """Переводит leet-speak в нормальный вид."""
    leet_map = {"4": "a", "3": "e", "0": "o", "1": "i", "5": "s", "7": "t", "@": "a"}
    result = nick.lower()
    for k, v in leet_map.items():
        result = result.replace(k, v)
    return result


def detect_gender_from_name(name):
    """Определяет пол по ФИО."""
    if not name:
        return None
    parts = name.split()
    if not parts:
        return None
    middle = parts[-1] if len(parts) >= 3 else None
    if middle:
        ml = middle.lower()
        if ml.endswith("ович") or ml.endswith("евич"):
            return "Мужской"
        if ml.endswith("овна") or ml.endswith("евна") or ml.endswith("ична"):
            return "Женский"
    return None


def detect_nationality(name):
    """Оценивает национальность по ФИО."""
    if not name:
        return None
    name_lower = name.lower()
    if "енко" in name_lower or name_lower.endswith("ук"):
        return "Украинская"
    if "ян" in name_lower:
        return "Армянская"
    if "дзе" in name_lower or "швили" in name_lower:
        return "Грузинская"
    if "оглы" in name_lower or "заде" in name_lower:
        return "Азербайджанская"
    if any(s in name_lower for s in ["ов", "ев", "ин", "ский", "цкий"]):
        return "Русская/славянская"
    return None


def country_from_email(email):
    """Страна по домену email."""
    if not email or "@" not in email:
        return None
    domain = email.split("@")[1].lower()
    mapping = {
        ".ru": "Россия", ".ua": "Украина", ".kz": "Казахстан",
        ".by": "Беларусь", ".de": "Германия", ".us": "США",
        ".uk": "Великобритания", ".fr": "Франция", ".it": "Италия",
        ".tr": "Турция", ".cn": "Китай", ".jp": "Япония",
        ".kr": "Корея", ".il": "Израиль", ".uz": "Узбекистан", ".ge": "Грузия",
    }
    for k, v in mapping.items():
        if domain.endswith(k):
            return v
    return None


def estimate_vk_registration(vk_id):
    """Оценка года регистрации VK по ID."""
    if not vk_id:
        return None
    try:
        vid = int(vk_id)
        if vid < 1000000:
            return "до 2007 (один из первых)"
        elif vid < 50000000:
            return "2007-2010"
        elif vid < 200000000:
            return "2010-2014"
        elif vid < 400000000:
            return "2014-2018"
        elif vid < 700000000:
            return "2018-2022"
        else:
            return "2022+ (новый)"
    except Exception:
        return None


def phone_info(phone):
    """Анализ номера."""
    try:
        import phonenumbers
        from phonenumbers import carrier, geocoder, timezone
    except ImportError:
        os.system(f"{os.sys.executable} -m pip install phonenumbers")
        import phonenumbers
        from phonenumbers import carrier, geocoder, timezone

    phone_clean = re.sub(r"[^\d+]", "", phone)
    if phone_clean.startswith("8"):
        phone_clean = "+7" + phone_clean[1:]
    if not phone_clean.startswith("+"):
        phone_clean = "+" + phone_clean

    r = {"input": phone_clean, "valid": False}

    try:
        parsed = phonenumbers.parse(phone_clean, None)
    except Exception:
        return r

    if not phonenumbers.is_valid_number(parsed):
        return r

    r["valid"] = True
    r["country"] = phonenumbers.region_code_for_number(parsed)
    r["operator"] = carrier.name_for_number(parsed, "ru")
    r["region"] = geocoder.description_for_number(parsed, "ru")
    tz = timezone.time_zones_for_number(parsed)
    r["timezone"] = list(tz)[0] if tz else None
    return r


def check_telegram(phone):
    """TG по номеру."""
    result = {"found": False, "name": None, "link": None, "bio": None}
    try:
        num = re.sub(r"[^\d]", "", phone)
        if num.startswith("8"):
            num = "7" + num[1:]
        link = "https://t.me/+" + num
        result["link"] = link
        r = requests.get(link, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        if "tgme_page_title" in r.text:
            m = re.search(r'<div class="tgme_page_title"[^>]*>([^<]+)</div>', r.text)
            if m:
                result["name"] = m.group(1).strip()
                result["found"] = True
    except Exception:
        pass
    return result


def check_username(nick):
    """Ник на платформах."""
    nick = nick.strip().lstrip("@")
    platforms = {
        "VK": f"https://vk.com/{nick}",
        "Telegram": f"https://t.me/{nick}",
        "TikTok": f"https://www.tiktok.com/@{nick}",
        "Instagram": f"https://www.instagram.com/{nick}",
        "GitHub": f"https://github.com/{nick}",
        "Twitter": f"https://twitter.com/{nick}",
        "YouTube": f"https://www.youtube.com/@{nick}",
        "Reddit": f"https://www.reddit.com/user/{nick}",
        "Pinterest": f"https://www.pinterest.com/{nick}",
        "Twitch": f"https://www.twitch.tv/{nick}",
    }
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    found = {}
    for name, url in platforms.items():
        try:
            rq = requests.head(url, headers=headers, timeout=8, allow_redirects=True)
            if rq.status_code == 200:
                found[name] = url
        except Exception:
            pass
    return found


def check_vk_id(vk_id):
    """VK ID → имя, город, ДР."""
    r = {"found": False}
    try:
        rq = requests.get(
            "https://api.vk.com/method/users.get",
            params={"user_ids": vk_id, "fields": "city,bdate,country,sex,status", "v": "5.131"},
            timeout=10
        )
        data = rq.json()
        if "response" in data and data["response"]:
            u = data["response"][0]
            r["found"] = True
            r["name"] = (u.get("first_name", "") + " " + u.get("last_name", "")).strip()
            if u.get("city"):
                r["city"] = u["city"].get("title")
            if u.get("bdate"):
                r["bdate"] = u["bdate"]
                parts = u["bdate"].split(".")
                if len(parts) == 3:
                    try:
                        year = int(parts[2])
                        r["birth_year"] = year
                        r["age"] = datetime.now().year - year
                    except Exception:
                        pass
            if u.get("status"):
                r["status"] = u["status"]
            if u.get("sex"):
                r["gender"] = "Мужской" if u["sex"] == 2 else "Женский"
    except Exception:
        pass
    return r


def check_whatsapp(phone):
    """WhatsApp."""
    try:
        num = re.sub(r"[^\d]", "", phone)
        link = "https://wa.me/" + num
        r = requests.get(link, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        if "WhatsApp" in r.text and "not on WhatsApp" not in r.text:
            return {"found": True, "link": link}
    except Exception:
        pass
    return {"found": False}


# ============================================================
#                ВАЛИДАЦИЯ
# ============================================================

def cross_validate(data):
    """Сравнивает зацепки из разных источников."""
    checks = []

    vk_info = data.get("vk_info") or {}
    phone_info = data.get("phone_info") or {}
    tg_info = data.get("tg_info") or {}
    wa_info = data.get("wa_info") or {}
    nick_platforms = data.get("nick_platforms") or {}
    nick_years = data.get("nick_years") or []
    nick_ages = data.get("nick_ages") or []

    # 1. Город VK vs регион номера
    if phone_info and vk_info and vk_info.get("found"):
        pr = (phone_info.get("region") or "").lower()
        vk_city = (vk_info.get("city") or "").lower()
        if pr and vk_city:
            if vk_city in pr or pr in vk_city:
                checks.append(("✅ Город VK совпадает с регионом: " + vk_city, "HIGH"))
            else:
                checks.append(("⚠️ Город VK (" + vk_city + ") не совпадает с регионом", "MED"))

    # 2. Год в нике vs ДР VK
    if nick_years and vk_info.get("birth_year"):
        vk_year = vk_info["birth_year"]
        if vk_year in nick_years:
            checks.append(("✅ Год в нике совпадает с ДР VK: " + str(vk_year), "HIGH"))
        else:
            checks.append(("⚠️ Год в нике не совпадает с ДР VK", "MED"))

    # 3. TG имя vs VK имя
    if tg_info.get("name") and vk_info.get("name"):
        tg = tg_info["name"].lower()
        vk = vk_info["name"].lower()
        if tg in vk or vk in tg or any(p in vk for p in tg.split()):
            checks.append(("✅ TG и VK имена совпадают: " + vk_info["name"], "HIGH"))
        else:
            checks.append(("⚠️ TG и VK имена разные", "MED"))

    # 4. Ник на нескольких платформах
    if nick_platforms:
        cnt = len(nick_platforms)
        if cnt >= 3:
            checks.append(("✅ Ник занят на " + str(cnt) + " платформах", "HIGH"))
        elif cnt == 1:
            checks.append(("⚠️ Ник только на 1 платформе", "LOW"))

    # 5. Email страна
    if data.get("email_country") and phone_info.get("country"):
        checks.append(("ℹ️ Email: " + str(data["email_country"]) + " | Номер: " + str(phone_info["country"]), "INFO"))

    # 6. Возраст VK vs ник
    if vk_info.get("age") and nick_ages:
        vk_age = vk_info["age"]
        for a in nick_ages:
            if isinstance(a, int) and abs(vk_age - a) <= 2:
                checks.append(("✅ Возраст в нике близок к VK: " + str(a), "HIGH"))
                break

    # 7. WhatsApp
    if wa_info.get("found"):
        checks.append(("✅ WhatsApp привязан к номеру", "HIGH"))

    return checks


# ============================================================
#                    СБОР
# ============================================================

def gather(phone=None, email=None, nick=None, vk_id=None):
    data = {
        "phone": phone, "email": email, "nick": nick, "vk_id": vk_id,
        "phone_info": None, "tg_info": None, "wa_info": None,
        "vk_info": None, "nick_platforms": None,
        "nick_years": [], "nick_ages": [],
        "nick_leet": None, "email_country": None,
        "gender": None, "nationality": None,
    }

    if phone:
        data["phone_info"] = phone_info(phone)
        data["tg_info"] = check_telegram(phone)
        data["wa_info"] = check_whatsapp(phone)

    if email:
        data["email_country"] = country_from_email(email)

    if nick:
        data["nick_platforms"] = check_username(nick)
        data["nick_years"] = extract_years_from_nick(nick)
        data["nick_ages"] = [x[1] for x in extract_short_dates(nick)]
        data["nick_leet"] = normalize_leet(nick)

    if vk_id:
        data["vk_info"] = check_vk_id(vk_id)
        if data["vk_info"] and data["vk_info"].get("name"):
            data["gender"] = detect_gender_from_name(data["vk_info"]["name"])
            data["nationality"] = detect_nationality(data["vk_info"]["name"])

    data["validation"] = cross_validate(data)
    return data


# ============================================================
#                    ОТЧЁТ
# ============================================================

def format_report(data):
    text = "🔍 OSINT ОТЧЁТ\n"
    text += "━━━━━━━━━━━━━━━━━━━━\n\n"

    # Ввод
    text += "📥 ВВОД:\n"
    if data.get("phone"): text += "  📱 " + str(data["phone"]) + "\n"
    if data.get("email"): text += "  📧 " + str(data["email"]) + "\n"
    if data.get("nick"): text += "  👤 " + str(data["nick"]) + "\n"
    if data.get("vk_id"): text += "  🆔 " + str(data["vk_id"]) + "\n"
    text += "\n"

    # Номер
    pi = data.get("phone_info") or {}
    if pi.get("valid"):
        text += "📱 ПО НОМЕРУ:\n"
        text += "  🌍 Страна: " + str(pi.get("country") or "?") + "\n"
        text += "  📡 Оператор: " + str(pi.get("operator") or "?") + "\n"
        text += "  🏙 Регион: " + str(pi.get("region") or "?") + "\n"
        text += "  🕐 TZ: " + str(pi.get("timezone") or "?") + "\n"
        wa = data.get("wa_info") or {}
        if wa.get("found"):
            text += "  📞 WhatsApp: ✅ есть\n"
        text += "\n"

    # TG
    tg = data.get("tg_info") or {}
    if tg.get("link"):
        text += "🔷 TELEGRAM:\n"
        if tg.get("found"):
            text += "  ✅ " + str(tg.get("name") or "?") + "\n"
            text += "  🔗 " + str(tg.get("link") or "?") + "\n"
        else:
            text += "  ❌ Не найден\n"
        text += "\n"

    # Ник
    np = data.get("nick_platforms") or {}
    if np:
        text += "👤 НИК НА ПЛАТФОРМАХ:\n"
        for p in np.keys():
            text += "  ✅ " + p + "\n"
        text += "\n"

    ny = data.get("nick_years") or []
    if ny:
        text += "🎂 ГОДЫ В НИКЕ:\n"
        for y in ny:
            text += "  • " + str(y) + "\n"
        text += "\n"

    leet = data.get("nick_leet")
    if leet and leet != (data.get("nick") or "").lower():
        text += "🔄 LEET-SPEAK: " + str(leet) + "\n\n"

    # VK
    vk = data.get("vk_info") or {}
    if vk.get("found"):
        text += "🆔 VK:\n"
        text += "  👤 Имя: " + str(vk.get("name") or "?") + "\n"
        if vk.get("city"): text += "  🏙 Город: " + str(vk["city"]) + "\n"
        if vk.get("bdate"): text += "  🎂 ДР: " + str(vk["bdate"]) + "\n"
        if vk.get("age"): text += "  📅 Возраст: " + str(vk["age"]) + "\n"
        if vk.get("gender"): text += "  ⚧ Пол: " + str(vk["gender"]) + "\n"
        if vk.get("status"): text += "  💬 Статус: " + str(vk["status"])[:80] + "\n"
        reg = estimate_vk_registration(data.get("vk_id"))
        if reg:
            text += "  📆 Регистрация: ~" + reg + "\n"
        text += "\n"

    # Email
    if data.get("email_country"):
        text += "📧 EMAIL:\n  🌍 " + str(data["email_country"]) + "\n\n"

    # Пол/нация
    if data.get("gender"):
        text += "⚧ ПОЛ: " + str(data["gender"]) + "\n"
    if data.get("nationality"):
        text += "🌐 НАЦИОНАЛЬНОСТЬ: " + str(data["nationality"]) + "\n"

    # ВАЛИДАЦИЯ
    text += "\n🎯 ВАЛИДАЦИЯ:\n"
    text += "━━━━━━━━━━━━━━━━━━━━\n"
    val = data.get("validation") or []
    if val:
        for msg, level in val:
            icon = "🟢" if level == "HIGH" else ("🟡" if level == "MED" else "⚪")
            text += icon + " " + msg + "\n"
    else:
        text += "⚠️ Недостаточно данных\n"

    return text


# ============================================================
#                    МЕНЮ
# ============================================================

def main_menu():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("🔍 Комбо", callback_data="os_combo"),
        types.InlineKeyboardButton("📱 Номер", callback_data="os_phone"),
    )
    markup.add(
        types.InlineKeyboardButton("📧 Email", callback_data="os_email"),
        types.InlineKeyboardButton("👤 Ник", callback_data="os_nick"),
    )
    markup.add(
        types.InlineKeyboardButton("🆔 VK ID", callback_data="os_vk"),
        types.InlineKeyboardButton("📛 ФИО", callback_data="os_fio"),
    )
    return markup


# ============================================================
#                    ОБРАБОТЧИКИ
# ============================================================

if bot:
    @bot.message_handler(commands=["start"])
    def cmd_start(message):
        text = (
            "🔍 OSINT БОТ — БЕСПЛАТНО\n\n"
            "Цепляюсь за мельчайшие зацепки:\n"
            "• Цифры в нике → год, возраст\n"
            "• Leet-speak в нике\n"
            "• Домен email → страна\n"
            "• VK ID → дата регистрации\n"
            "• Регион номера + город VK\n"
            "• Кросс-валидация всех источников\n\n"
            "Всё бесплатно, без подписки."
        )
        bot.send_message(message.chat.id, text, reply_markup=main_menu())

    @bot.message_handler(commands=["menu"])
    def cmd_menu(message):
        bot.send_message(message.chat.id, "Меню:", reply_markup=main_menu())

    @bot.callback_query_handler(func=lambda call: call.data == "os_combo")
    def cb_combo(call):
        bot.answer_callback_query(call.id)
        msg = bot.send_message(
            call.message.chat.id,
            "Введи данные (каждое с новой строки):\n"
            "номер, email, ник, VK ID\n\n"
            "Пример:\n"
            "+79963132197\n"
            "test@mail.ru\n"
            "username\n"
            "123456789"
        )
        bot.register_next_step_handler(msg, process_combo)

    def process_combo(message):
        lines = [l.strip() for l in message.text.split("\n") if l.strip()]
        phone = email = nick = vk_id = None

        for l in lines:
            if re.match(r"^\+?[\d\s\-\(\)]{10,}$", l):
                phone = l
            elif "@" in l and "." in l:
                email = l
            elif re.match(r"^\d{5,12}$", l):
                vk_id = l
            else:
                nick = l

        bot.send_message(message.chat.id, "🔍 Собираю зацепки...")
        try:
            data = gather(phone=phone, email=email, nick=nick, vk_id=vk_id)
            report = format_report(data)
            if len(report) > 4000:
                for i in range(0, len(report), 4000):
                    bot.send_message(message.chat.id, report[i:i+4000])
            else:
                bot.send_message(message.chat.id, report)
        except Exception as e:
            bot.send_message(message.chat.id, "❌ Ошибка: " + str(e)[:200])

    @bot.callback_query_handler(func=lambda call: call.data == "os_phone")
    def cb_phone(call):
        bot.answer_callback_query(call.id)
        msg = bot.send_message(call.message.chat.id, "Введи номер:")
        bot.register_next_step_handler(msg, process_phone)

    def process_phone(message):
        bot.send_message(message.chat.id, "🔍 Собираю...")
        try:
            data = gather(phone=message.text.strip())
            bot.send_message(message.chat.id, format_report(data))
        except Exception as e:
            bot.send_message(message.chat.id, "❌ " + str(e)[:200])

    @bot.callback_query_handler(func=lambda call: call.data == "os_email")
    def cb_email(call):
        bot.answer_callback_query(call.id)
        msg = bot.send_message(call.message.chat.id, "Введи email:")
        bot.register_next_step_handler(msg, process_email)

    def process_email(message):
        bot.send_message(message.chat.id, "🔍 Собираю...")
        try:
            data = gather(email=message.text.strip())
            bot.send_message(message.chat.id, format_report(data))
        except Exception as e:
            bot.send_message(message.chat.id, "❌ " + str(e)[:200])

    @bot.callback_query_handler(func=lambda call: call.data == "os_nick")
    def cb_nick(call):
        bot.answer_callback_query(call.id)
        msg = bot.send_message(call.message.chat.id, "Введи ник:")
        bot.register_next_step_handler(msg, process_nick)

    def process_nick(message):
        bot.send_message(message.chat.id, "🔍 Собираю...")
        try:
            data = gather(nick=message.text.strip())
            bot.send_message(message.chat.id, format_report(data))
        except Exception as e:
            bot.send_message(message.chat.id, "❌ " + str(e)[:200])

    @bot.callback_query_handler(func=lambda call: call.data == "os_vk")
    def cb_vk(call):
        bot.answer_callback_query(call.id)
        msg = bot.send_message(call.message.chat.id, "Введи VK ID:")
        bot.register_next_step_handler(msg, process_vk)

    def process_vk(message):
        bot.send_message(message.chat.id, "🔍 Собираю...")
        try:
            data = gather(vk_id=message.text.strip())
            bot.send_message(message.chat.id, format_report(data))
        except Exception as e:
            bot.send_message(message.chat.id, "❌ " + str(e)[:200])

    @bot.callback_query_handler(func=lambda call: call.data == "os_fio")
    def cb_fio(call):
        bot.answer_callback_query(call.id)
        msg = bot.send_message(call.message.chat.id, "Введи ФИО:")
        bot.register_next_step_handler(msg, process_fio)

    def process_fio(message):
        fio = message.text.strip()
        gender = detect_gender_from_name(fio)
        nationality = detect_nationality(fio)
        text = "📛 ФИО: " + fio + "\n\n"
        if gender:
            text += "⚧ Пол: " + gender + "\n"
        if nationality:
            text += "🌐 Национальность: " + nationality + "\n"
        text += "\n⚠️ Для полной инфы добавь VK ID."
        bot.send_message(message.chat.id, text)


# ============ WEBHOOK ============
@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        json_str = request.get_data().decode("utf-8")
        update = telebot.types.Update.de_json(json_str)
        bot.process_new_updates([update])
    except Exception as e:
        print("[ERROR] webhook: " + str(e))
    return "OK", 200


def set_webhook():
    try:
        import requests as rq
        render_url = os.environ.get("RENDER_EXTERNAL_URL", "")
        if not render_url:
            return False
        webhook_url = render_url + "/webhook"
        resp = rq.post(
            "https://api.telegram.org/bot" + BOT_TOKEN + "/setWebhook",
            json={"url": webhook_url, "allowed_updates": ["message", "callback_query"]}
        )
        print("[+] Webhook: " + str(resp.json()))
        return True
    except Exception as e:
        print("[ERROR] set_webhook: " + str(e))
        return False


if __name__ == "__main__":
    print("[+] Запускаю Flask...")
    t = Thread(target=run_web)
    t.daemon = True
    t.start()
    if bot:
        time.sleep(3)
        print("[+] Устанавливаю webhook...")
        set_webhook()
        print("[+] Бот запущен")
        while True:
            time.sleep(60)
    else:
        while True:
            time.sleep(60)
