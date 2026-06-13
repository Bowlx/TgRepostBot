# TgRepostBot

Telegram → LinkedIn кросспостинг бот с опциональным переводом.

## Возможности

- 🔄 Автоматический кросспостинг из Telegram каналов в LinkedIn
- 📝 Ручная пересылка постов через бота
- 🌐 Перевод через MyMemory — **бесплатно, без карты и API ключа** (можно отключить)
- 🖼️ Перенос изображений
- ⚙️ Полная настройка через Telegram — без редактирования файлов
- 🐙 Пошаговый wizard `/setup` для новичков

## Быстрый старт (3 команды)

```bash
git clone https://github.com/Bowlx/TgRepostBot ~/TgRepostBot
cd ~/TgRepostBot
cp .env.example .env && nano .env   # вставить только BOT_TOKEN
docker compose up -d
```

Всё! Остальное настраивается прямо в Telegram через `/setup`.

## Пошаговая установка на VPS

### Шаг 1: Подготовка сервера

```bash
sudo apt update && sudo apt upgrade -y

# Установите Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER
# Выйдите из SSH и зайдите снова
```

### Шаг 2: Единственная настройка на сервере

```bash
git clone https://github.com/Bowlx/TgRepostBot ~/TgRepostBot
cd ~/TgRepostBot
cp .env.example .env
nano .env
```

В `.env` нужно указать **только одну переменную**:

```
BOT_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
```

> Токен бота: [@BotFather](https://t.me/BotFather) → `/newbot`

### Шаг 3: Запуск

```bash
docker compose up -d
docker compose logs -f    # проверить что запустился
```

### Шаг 4: Настройка через Telegram (wizard)

1. Откройте бота в Telegram → нажмите **Start**
2. Бот увидит, что не настроен → нажмите **🚀 Настроить бот**
3. Пройдите 3 шага wizard'а (только LinkedIn — переводчик уже работает):
   - 🆔 **LinkedIn Client ID**
   - 🔐 **LinkedIn Client Secret**
   - 🔗 **LinkedIn Redirect URI**
4. После wizard'а → нажмите **🔗 Подключить LinkedIn** → разрешите доступ
5. Скопируйте `code` из URL редиректа → отправьте `/callback ВАШ_КОД`
6. Готово! 🎉

> Перевод работает **сразу** через MyMemory — ничего настраивать не нужно.
> По желанию: `/translate off` отключит перевод, `/setemail ваш@email` поднимет лимит до 50 000 симв/день.

## Как получить LinkedIn ключи (подробно)

<details>
<summary>💼 LinkedIn App (Client ID + Secret)</summary>

1. Откройте [LinkedIn Developers](https://www.linkedin.com/developers/)
2. Нажмите **Create App**
3. Заполните: название, LinkedIn Page, язык
4. В разделе **Settings** → подтвердите приложение (**Verify**)
5. В разделе **Products** включите **ОБА** продукта:
   - **Share on LinkedIn** (для публикации постов)
   - **Sign In with LinkedIn using OpenID Connect** (для получения ID пользователя)
6. В разделе **Auth**:
   - Добавьте Redirect URL: `https://localhost` (для тестирования) или ваш домен
   - Скопируйте **Client ID** и **Client Secret**

</details>

## Команды бота

| Команда | Описание |
|---------|----------|
| `/start` | Приветствие + статус настройки |
| `/setup` | Пошаговая настройка LinkedIn |
| `/auth` | Подключить LinkedIn аккаунт |
| `/callback CODE` | Завершить авторизацию LinkedIn |
| `/setlang SRC TGT` | Языки перевода (например: `ru en`) |
| `/translate on\|off` | Включить/отключить перевод |
| `/setemail ваш@email` | Повысить лимит переводов до 50k симв/день |
| `/preview` | Превью отложенного поста |
| `/post` | Опубликовать отложенный пост в LinkedIn |
| `/skip` | Отменить отложенный пост |

## Перевод (опционально)

Бот использует **MyMemory API** — бесплатно, без ключа, без карты.

| Настройка | Лимит |
|-----------|-------|
| По умолчанию (анонимно) | 5 000 симв/день |
| С `/setemail ваш@email` | 50 000 симв/день |

- `/translate off` — публиковать посты в оригинале без перевода
- `/translate on` — снова включить перевод (по умолчанию)

## Управление Docker

```bash
docker compose down              # остановить
docker compose restart           # перезапустить
docker compose up -d --build     # обновить после git pull
docker compose logs -f --tail 100  # логи
```

## Режимы работы

### Автоматический (из канала)

Добавьте бота как подписчика в Telegram канал. Все новые посты будут автоматически публиковаться в LinkedIn (с переводом, если включён).

### Ручной (пересылка)

Перешлите любой пост боту в личные сообщения. Бот покажет превью (с переводом, если включён). Нажмите `/post` для публикации или `/skip` для отмены.

## Обновление

```bash
cd ~/TgRepostBot
git pull
docker compose up -d --build
```

> База данных (`data/bot.db`) хранится в Docker volume — не теряется при обновлении.
