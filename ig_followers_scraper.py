# ig_followers_scraper_login.py
import os
import time
import re
import random
import pandas as pd
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# ---------- CONFIG ----------
TARGET = "erik.mendozafu"         # perfil objetivo (público)
MAX_FOLLOWERS_TO_SCRAPE = 4000    # máximo de seguidores a extraer
SCROLL_PAUSE = (1.2, 2.4)         # pausa aleatoria entre scrolls
OUTPUT_FILE = "instagram_followers.xlsx"
STORAGE = "auth.json"             # sesión guardada

IG_USER = os.environ.get("IG_USER")
IG_PASS = os.environ.get("IG_PASS")
HEADLESS = os.environ.get("HEADLESS", "False").lower() in ("1", "true", "yes")

if not IG_USER or not IG_PASS:
    print("❌ Por favor exporta IG_USER e IG_PASS antes de ejecutar.")
    print("   ej: export IG_USER='tu_usuario' && export IG_PASS='tu_password'")
    raise SystemExit(1)


# ---------- FUNCIONES ----------

def human_scroll_modal(page, scroll_box, max_followers):
    """Hace scroll humano dentro del modal."""
    followers = set()
    stagnant_scrolls = 0
    last_count = 0

    while len(followers) < max_followers:
        # Extraer usernames visibles
        elements = scroll_box.query_selector_all('a[role="link"][href*="/"] span')
        for el in elements:
            try:
                username = el.inner_text().strip()
                if username and username not in followers and not username.startswith("#"):
                    followers.add(username)
                    print(f" → {username}")
                    if len(followers) >= max_followers:
                        break
            except Exception:
                continue

        # Simular scroll humano (mouse wheel)
        try:
            scroll_box.hover()
            page.mouse.wheel(0, random.randint(500, 800))
        except Exception:
            break

        time.sleep(random.uniform(*SCROLL_PAUSE))

        # Verificar si siguen cargando más
        if len(followers) == last_count:
            stagnant_scrolls += 1
        else:
            stagnant_scrolls = 0
        last_count = len(followers)

        if stagnant_scrolls >= 6:
            print("📉 No se detectan más nuevos seguidores cargando.")
            break

    print(f"✅ Total de seguidores encontrados: {len(followers)}")
    return list(followers)


def parse_followers_from_modal(page, max_followers=4000):
    print("📥 Extrayendo lista de seguidores...")

    page.wait_for_selector('div[role="dialog"]', timeout=30000)

    scroll_box = None
    possible_selectors = [
        'div[role="dialog"] div[style*="overflow-y: auto"]',
        'div[role="dialog"] div._aano',
        'div[role="dialog"] div.x9f619',
        'div[role="dialog"] div.x6nl9eh',
        'div[role="dialog"] div.x6nl9eh.x1a5l9x9.x7vuprf.x1mg3h75.'
        'x1lliihq.x1iyjqo2.xs83m0k.xz65tgg.x1rife3k.x1n2onr6'
    ]

    for selector in possible_selectors:
        try:
            el = page.query_selector(selector)
            if el:
                scroll_box = el
                print(f"✅ Contenedor de scroll detectado: {selector}")
                break
        except Exception:
            continue

    if not scroll_box:
        print("❌ No se encontró el contenedor de scroll del modal (estructura nueva detectada).")
        print("💡 Abre el modal manualmente y revisa el div con overflow-y: auto.")
        return []

    # Scroll humano dentro del modal
    return human_scroll_modal(page, scroll_box, max_followers)


def get_follower_count_from_profile(page, username):
    """Ir al perfil y extraer su número de seguidores."""
    profile_url = f"https://www.instagram.com/{username}/"
    try:
        page.goto(profile_url, timeout=30000)
    except PWTimeout:
        print(f"⚠️ Timeout al cargar {username}")
        return None
    time.sleep(1.8)

    # Intento 1: meta description
    try:
        meta = page.query_selector('meta[name="description"]')
        if meta:
            content = meta.get_attribute('content') or ""
            m = re.search(r'([\d,\.]+)\s+Followers', content)
            if m:
                num = m.group(1).replace(',', '').replace('.', '')
                return int(num)
    except Exception:
        pass

    # Intento 2: JSON embebido
    try:
        html = page.content()
        m2 = re.search(r'"edge_followed_by":\s*{\s*"count":\s*([0-9]+)', html)
        if m2:
            return int(m2.group(1))
    except Exception:
        pass

    return None


def login_and_get_context(playwright):
    """Inicia sesión o carga una sesión persistente."""
    browser = playwright.chromium.launch(headless=HEADLESS)
    context = browser.new_context(locale="en-US",
                                  user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                             "AppleWebKit/537.36 (KHTML, like Gecko) "
                                             "Chrome/115.0 Safari/537.36")
    page = context.new_page()

    if os.path.exists(STORAGE):
        print("🔑 Usando sesión guardada.")
        context = playwright.chromium.launch_persistent_context(
            user_data_dir="userdata", headless=HEADLESS, locale="en-US"
        )
        return context, context.pages[0] if context.pages else context.new_page()

    print("🌐 Navegando a Instagram para login...")
    page.goto("https://www.instagram.com/accounts/login/", timeout=60000)
    page.wait_for_selector('input[name="username"]', timeout=30000)
    page.fill('input[name="username"]', IG_USER)
    page.fill('input[name="password"]', IG_PASS)
    page.click('button[type="submit"]')

    try:
        page.wait_for_url(re.compile(r"instagram\.com/"), timeout=40000)
    except Exception:
        pass

    time.sleep(4)
    for text in ["Not Now", "Ahora no"]:
        try:
            btn = page.query_selector(f'button:has-text("{text}")')
            if btn:
                btn.click()
                time.sleep(1)
        except Exception:
            pass

    context.storage_state(path=STORAGE)
    print(f"💾 Sesión guardada en {STORAGE}")
    return context, page


# ---------- MAIN ----------

def main():
    results = []

    with sync_playwright() as p:
        if os.path.exists(STORAGE):
            print("🔁 Cargando sesión desde archivo...")
            browser = p.chromium.launch(headless=HEADLESS)
            context = browser.new_context(storage_state=STORAGE, locale="en-US")
            page = context.new_page()
        else:
            context, page = login_and_get_context(p)

        print(f"📍 Visitando perfil: {TARGET}")
        page.goto(f"https://www.instagram.com/{TARGET}/", timeout=30000)
        time.sleep(4)

        # Abrir modal de seguidores
        try:
            followers_link = page.query_selector('a[href$="/followers/"], a[href*="/followers/"]')
            if followers_link:
                followers_link.click()
            else:
                page.click('header section ul li:nth-child(2)')
            print("👥 Abriendo modal de seguidores...")
            page.wait_for_selector('div[role="dialog"]', timeout=10000)
            time.sleep(3)
        except Exception as e:
            print(f"❌ Error al abrir modal de followers: {e}")
            context.close()
            return

        usernames = parse_followers_from_modal(page, MAX_FOLLOWERS_TO_SCRAPE)
        print(f"📊 {len(usernames)} seguidores extraídos (límite {MAX_FOLLOWERS_TO_SCRAPE})")

        for i, u in enumerate(usernames, start=1):
            count = get_follower_count_from_profile(page, u)
            print(f"{i}/{len(usernames)} - {u}: {count}")
            results.append({
                "username": u,
                "followers_count": count,
                "profile_url": f"https://www.instagram.com/{u}/"
            })
            time.sleep(1)

        context.close()

    df = pd.DataFrame(results)
    df.to_excel(OUTPUT_FILE, index=False)
    print(f"✅ Datos guardados en {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
