# TgRepostBot

Telegram → LinkedIn кросспостинг бот с автоматическим переводом.

## Возможности

- 🔄 Автоматический кросспостинг из Telegram каналов в LinkedIn
- 📝 Ручная пересылка постов через бота
- 🌐 Автоматический перевод текста (Google Translate)
- 🖼️ Перенос изображений
- ⚙️ Настраиваемые языковые пары

## Предварительные требования

### 1. Создать Telegram бота

1. Откройте [@BotFather](https://t.me/BotFather) в Telegram
2. Отправьте `/newbot` и следуйте инструкциям
3. Скопируйте полученный **BOT_TOKEN**

### 2. Создать LinkedIn App

1. Перейдите на [LinkedIn Developers](https://www.linkedin.com/developers/)
2. Нажмите **Create App**
3. Заполните данные приложения
4. В разделе **Products** включите **Share on LinkedIn**
5. В разделе **Auth** добавьте Redirect URL (например, `https://your-domain.com/callback`)
6. Скопируйте **Client ID** и **Client Secret**

### 3. Получить Google Translate API Key

1. Перейдите в [Google Cloud Console](https://console.cloud.google.com/)
2. Создайте проект (или выберите существующий)
3. Включите **Cloud Translation API**
4. Перейдите в **APIs & Services → Credentials**
5. Создайте **API Key**
6. Скопируйте ключ

## Установка на VPS

### Шаг 1: Подготовка сервера

```bash
# Обновите систему
sudo apt update && sudo apt upgrade -y

# Установите Docker и Docker Compose
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER
# Выйдите и зайдите снова для применения группы
```

### Шаг 2: Клонирование и настройка

```bash
# Клонируйте репозиторий
git clone <YOUR_REPO_URL> ~/TgRepostBot
cd ~/TgRepostBot

# Создайте .env файл из шаблона
cp .env.example .env

# Отредактируйте .env файл
nano .env
```

Заполните `.env` вашими значениями:

```
BOT_TOKEN=ваш_токен_от_botfather
LINKEDIN_CLIENT_ID=ваш_linkedin_client_id
LINKEDIN_CLIENT_SECRET=ваш_linkedin_client_secret
LINKEDIN_REDIRECT_URI=https://your-domain.com/callback
GOOGLE_TRANSLATE_API_KEY=ваш_google_api_key
DATABASE_PATH=data/bot.db
DEFAULT_SOURCE_LANG=ru
DEFAULT_TARGET_LANG=en
```

### Шаг 3: Запуск

```bash
# Соберите и запустите
docker compose up -d

# Проверьте логи
docker compose logs -f
```

### Шаг 4: Настройка бота

1. Откройте бота в Telegram
2. Отправьте `/start`
3. Отправьте `/auth` и подключите LinkedIn
4. Настройте языки: `/setlang ru en`
5. Готово! Перешлите пост боту или добавьте его в канал

## Команды бота

| Команда | Описание |
|---------|----------|
| `/start` | Начать работу с ботом |
| `/auth` | Подключить LinkedIn |
| `/callback CODE` | Завершить авторизацию LinkedIn |
| `/setlang SRC TGT` | Настроить языки перевода (например: `ru en`) |
| `/preview` | Посмотреть превью отложенного поста |
| `/post` | Опубликовать отложенный пост в LinkedIn |
| `/skip` | Отменить отложенный пост |

## Управление

```bash
# Остановить бота
docker compose down

# Перезапустить
docker compose restart

# Обновить после изменений в коде
docker compose up -d --build

# Посмотреть логи
docker compose logs -f --tail 100
```

## Режимы работы

### Автоматический (из канала)

Добавьте бота как подписчика в Telegram канал. Все новые посты будут автоматически переводиться и публиковаться в LinkedIn.

### Ручной (пересылка)

Перешлите любой пост боту в личные сообщения. Бот переведёт текст и покажет превью. Нажмите `/post` для публикации или `/skip` для отмены.
