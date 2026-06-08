# TgRepostBot

Telegram → LinkedIn кросспостинг бот с автоматическим переводом.

## Возможности

- 🔄 Автоматический кросспостинг из Telegram каналов в LinkedIn
- 📝 Ручная пересылка постов через бота
- 🌐 Автоматический перевод текста (Google Translate)
- 🖼️ Перенос изображений
- ⚙️ Полная настройка через Telegram — без редактирования файлов
- 🐙 Пошаговый wizard `/setup` для новичков

## Быстрый старт (3 команды)

```bash
git clone <YOUR_REPO_URL> ~/TgRepostBot
cd ~/TgRepostBot
cp .env.example .env && nano .env   # вставить только BOT_TOKEN
docker compose up -d
```

Всё! Остальное настраивается прямо в Telegram через `/setup`.

## Пошаговая установка на VPS

### Шаг 1: Подготовка сервера

```bash
# Обновите систему
sudo apt update && sudo apt upgrade -y

# Установите Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER
# Выйдите из SSH и зайдите снова
```

### Шаг 2: Единственная настройка на сервере

```bash
git clone <YOUR_REPO_URL> ~/TgRepostBot
cd ~/TgRepostBot
cp .env.example .env
nano .env
```

В `.env` нужно указать **только одну переменную**:

```
BOT_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
```

> Токен бота можно получить у [@BotFather](https://t.me/BotFather) → `/newbot`

### Шаг 3: Запуск

```bash
docker compose up -d
docker compose logs -f    # проверить что запустился
```

### Шаг 4: Настройка через Telegram (wizard)

1. Откройте бота в Telegram → нажмите **Start**
2. Бот увидит, что не настроен → нажмите **🚀 Настроить бот**
3. Пройдите 4 шага wizard'а:
   - 🔑 **Google Translate API Key** — бот даст ссылку и инструкцию
   - 🆔 **LinkedIn Client ID** — ссылка на LinkedIn Developers + инструкция
   - 🔐 **LinkedIn Client Secret**
   - 🔗 **LinkedIn Redirect URI**
4. После wizard'а → нажмите **🔗 Подключить LinkedIn** → разрешите доступ
5. Скопируйте `code` из URL → отправьте `/callback ВАШ_КОД`
6. Готово! 🎉

### Как получить API ключи (подробно)

<details>
<summary>🔑 Google Translate API Key</summary>

1. Откройте [Google Cloud Console](https://console.cloud.google.com/)
2. Создайте проект (или выберите существующий)
3. В поиске введите **Cloud Translation API** → включите
4. Перейдите в **APIs & Services → Credentials**
5. Нажмите **Create Credentials → API Key**
6. Скопируйте ключ

</details>

<details>
<summary>💼 LinkedIn App (Client ID + Secret)</summary>

1. Откройте [LinkedIn Developers](https://www.linkedin.com/developers/)
2. Нажмите **Create App**
3. Заполните: название, LinkedIn Page, язык
4. В разделе **Products** включите **Share on LinkedIn**
5. В разделе **Auth**:
   - Добавьте Redirect URL: `https://localhost` (для тестирования) или ваш домен
   - Скопируйте **Client ID** и **Client Secret**

</details>

## Команды бота

| Команда | Описание |
|---------|----------|
| `/start` | Приветствие + статус настройки |
| `/setup` | Пошаговая настройка API ключей |
| `/auth` | Подключить LinkedIn аккаунт |
| `/callback CODE` | Завершить авторизацию LinkedIn |
| `/setlang SRC TGT` | Настроить языки перевода (например: `ru en`) |
| `/preview` | Посмотреть превью отложенного поста |
| `/post` | Опубликовать отложенный пост в LinkedIn |
| `/skip` | Отменить отложенный пост |

## Управление Docker

```bash
docker compose down              # остановить
docker compose restart           # перезапустить
docker compose up -d --build     # обновить после изменений
docker compose logs -f --tail 100  # логи
```

## Режимы работы

### Автоматический (из канала)

Добавьте бота как подписчика в Telegram канал. Все новые посты будут автоматически переводиться и публиковаться в LinkedIn.

### Ручной (пересылка)

Перешлите любой пост боту в личные сообщения. Бот переведёт текст и покажет превью. Нажмите `/post` для публикации или `/skip` для отмены.
