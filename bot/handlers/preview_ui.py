"""Unified post-preview button UI for both manual-forward and channel-approval flows.

Preview layout:
    [💼 LinkedIn 🟢/⏸] [📸 Instagram 🟢/⏸]   ← per-post destination toggles (connected only)
    [🌐 Оригинал] [🔤 Перевод] [✏️ Своё]      ← choose the text to publish
    [✏️ Изменить]                              ← only when custom text is active
    [❌ Отменить]
    [✅ Опубликовать]

The destination row inherits the user's global toggles when the post is created,
then can be overridden per-post — without touching the global settings.

Record kinds: 'm' = manual (pending_posts), 'a' = approval (pending_approvals).
callback_data: pv:{kind}:{id}:{action}[:dest]  action ∈ {o,t,c,x,p,d}, dest ∈ {li,ig}
"""
import logging

from aiogram import Router, types, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from models import User
from services.storage import Storage
from services.publisher import Publisher, render_results

router = Router()
logger = logging.getLogger(__name__)


class CustomText(StatesGroup):
    waiting = State()


# ── Record access (unified over the two pending tables) ────


async def _get_record(storage: Storage, kind: str, record_id: int):
    if kind == "a":
        return await storage.get_approval(record_id)
    return await storage.get_pending_post(record_id)


async def _set_active(storage: Storage, kind: str, record_id: int, mode: str, text: str) -> None:
    if kind == "a":
        await storage.set_approval_active(record_id, mode, text)
    else:
        await storage.set_pending_active(record_id, mode, text)


async def _set_dest(storage: Storage, kind: str, record_id: int, dest: str, enabled: bool) -> None:
    if kind == "a":
        await storage.set_approval_dest(record_id, dest, enabled)
    else:
        await storage.set_pending_dest(record_id, dest, enabled)


async def _delete(storage: Storage, kind: str, record_id: int) -> None:
    if kind == "a":
        await storage.delete_approval(record_id)
    else:
        await storage.delete_pending_post(record_id)


# ── Rendering ──────────────────────────────────────────────


def _src_btn(label: str, kind: str, rid: int, action: str, active: bool) -> InlineKeyboardButton:
    text = f"✅ {label}" if active else label
    data = f"pv:{kind}:{rid}:{action}"
    if active:
        return InlineKeyboardButton(text=text, callback_data=data, style="success")
    return InlineKeyboardButton(text=text, callback_data=data)


def _dest_btn(label: str, kind: str, rid: int, dest: str, on: bool) -> InlineKeyboardButton:
    text = f"{label} {'🟢' if on else '⏸'}"
    data = f"pv:{kind}:{rid}:d:{dest}"
    if on:
        return InlineKeyboardButton(text=text, callback_data=data, style="success")
    return InlineKeyboardButton(text=text, callback_data=data)


def preview_keyboard(kind: str, rid: int, record, user: User) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []

    # Row 0: per-post destination toggles (only for connected destinations).
    dest_row: list[InlineKeyboardButton] = []
    if user.linkedin_access_token:
        dest_row.append(_dest_btn("💼 LinkedIn", kind, rid, "li", record.li_enabled))
    ig_connected = bool(user.instagram_username or user.instagram_sessionid_encrypted)
    if ig_connected:
        dest_row.append(_dest_btn("📸 Instagram", kind, rid, "ig", record.ig_enabled))
    if dest_row:
        rows.append(dest_row)

    # Text source row.
    rows.append([
        _src_btn("🌐 Оригинал", kind, rid, "o", record.active_mode == "original"),
        _src_btn("🔤 Перевод", kind, rid, "t", record.active_mode == "translated"),
        _src_btn("✏️ Своё", kind, rid, "c", record.active_mode == "custom"),
    ])
    if record.active_mode == "custom":
        rows.append([InlineKeyboardButton(text="✏️ Изменить", callback_data=f"pv:{kind}:{rid}:c")])
    rows.append([InlineKeyboardButton(text="❌ Отменить", callback_data=f"pv:{kind}:{rid}:x")])
    rows.append([InlineKeyboardButton(text="✅ Опубликовать", callback_data=f"pv:{kind}:{rid}:p", style="primary")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def preview_text(record, kind: str) -> str:
    title = "📋 Превью поста" if kind == "m" else "🆕 Пост из канала"
    text = f"<b>{title}</b>\n\n{record.active_text or record.translated_text}\n\n"
    if record.photo_file_ids:
        text += f"🖼️ Изображений: {len(record.photo_file_ids)} шт.\n\n"
    return text


# ── Callback router ────────────────────────────────────────


@router.callback_query(F.data.startswith("pv:"))
async def handle_preview_callback(
    callback: types.CallbackQuery,
    state: FSMContext,
    bot: Bot,
    storage: Storage,
    publisher: Publisher,
) -> None:
    parts = callback.data.split(":")
    # parts: [pv, kind, id, action, (dest for 'd')]
    kind = parts[1]
    rid = int(parts[2])
    action = parts[3]
    dest = parts[4] if len(parts) > 4 else None

    record = await _get_record(storage, kind, rid)
    if record is None or record.user_id != callback.from_user.id:
        await callback.answer("Пост уже обработан или недоступен ❌", show_alert=True)
        return

    if action == "d":
        new_val = not (record.li_enabled if dest == "li" else record.ig_enabled)
        await _set_dest(storage, kind, rid, dest, new_val)
        await _refresh(callback, storage, kind, rid)
    elif action == "o":
        await _set_active(storage, kind, rid, "original", record.original_text)
        await _refresh(callback, storage, kind, rid)
    elif action == "t":
        await _set_active(storage, kind, rid, "translated", record.translated_text)
        await _refresh(callback, storage, kind, rid)
    elif action == "c":
        await _start_custom(callback, state, kind, rid, record)
    elif action == "x":
        await _cancel(callback, storage, kind, rid)
    elif action == "p":
        await _publish(callback, bot, storage, publisher, kind, rid)

    await callback.answer()


async def _refresh(callback, storage, kind, rid) -> None:
    record = await _get_record(storage, kind, rid)
    if record is None:
        return
    user = await storage.get_user(record.user_id)
    try:
        await callback.message.edit_text(
            preview_text(record, kind),
            reply_markup=preview_keyboard(kind, rid, record, user),
        )
    except Exception as e:
        logger.debug(f"preview refresh no-op: {e}")


async def _start_custom(callback, state, kind, rid, record) -> None:
    await state.set_state(CustomText.waiting)
    ref = await callback.message.answer(
        f"📋 <b>Текущий текст</b> (скопируйте и отредактируйте):\n\n"
        f"{record.active_text}\n\n"
        f"✏️ Пришлите новый текст. /cancel — оставить текущий."
    )
    await state.update_data(kind=kind, rid=rid, msg_id=callback.message.message_id, ref_id=ref.message_id)


async def _cancel(callback, storage, kind, rid) -> None:
    await _delete(storage, kind, rid)
    try:
        await callback.message.edit_text("🗑️ Пост отменён.")
    except Exception:
        pass


async def _publish(callback, bot, storage, publisher, kind, rid) -> None:
    record = await _get_record(storage, kind, rid)
    if record is None:
        await callback.message.edit_text("❌ Пост уже недоступен.")
        return
    user = await storage.get_user(record.user_id)
    if user is None:
        await callback.message.edit_text("❌ Пользователь не найден.")
        return

    await callback.message.edit_text("⏳ Публикую...")
    results = await publisher.publish_to_all(
        user,
        record.active_text or record.translated_text,
        record.photo_file_ids,
        li_enabled=record.li_enabled,
        ig_enabled=record.ig_enabled,
    )
    if any(r.ok for r in results):
        await _delete(storage, kind, rid)
        await callback.message.edit_text("✅ Готово!\n" + render_results(results))
    else:
        await callback.message.edit_text(
            "❌ Ни один destination не сработал:\n" + render_results(results)
        )


# ── Custom-text FSM ────────────────────────────────────────


async def _delete_safe(bot: Bot, chat_id: int, message_id: int) -> None:
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception as e:
        logger.debug(f"delete {message_id} failed: {e}")


@router.message(CustomText.waiting, F.text.lower() == "/cancel")
async def cancel_custom(message: types.Message, state: FSMContext, storage: Storage, bot: Bot) -> None:
    data = await state.get_data()
    await state.clear()
    if data.get("ref_id"):
        await _delete_safe(bot, message.chat.id, data["ref_id"])
    await _delete_safe(bot, message.chat.id, message.message_id)
    await message.answer("Редактирование отменено, текст не изменён.")


@router.message(CustomText.waiting, F.text)
async def receive_custom_text(message: types.Message, state: FSMContext, storage: Storage, bot: Bot) -> None:
    from bot.text_format import format_text

    data = await state.get_data()
    await state.clear()
    kind = data.get("kind")
    rid = data.get("rid")
    msg_id = data.get("msg_id")
    ref_id = data.get("ref_id")
    record = await _get_record(storage, kind, rid) if (kind and rid) else None

    if ref_id:
        await _delete_safe(bot, message.chat.id, ref_id)
    await _delete_safe(bot, message.chat.id, message.message_id)

    if record is None:
        await message.answer("❌ Пост уже недоступен.")
        return

    new_text = format_text(message.text)
    await _set_active(storage, kind, rid, "custom", new_text)
    record.active_text = new_text
    record.active_mode = "custom"

    user = await storage.get_user(record.user_id)
    if msg_id:
        try:
            await bot.edit_message_text(
                preview_text(record, kind),
                chat_id=message.chat.id,
                message_id=msg_id,
                reply_markup=preview_keyboard(kind, rid, record, user),
            )
            return
        except Exception:
            pass
    await message.answer(
        preview_text(record, kind), reply_markup=preview_keyboard(kind, rid, record, user)
    )
