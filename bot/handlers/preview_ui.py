"""Unified post-preview button UI for both manual-forward and channel-approval flows.

Preview message layout:
    [🌐 Оригинал] [🔤 Перевод] [✏️ Своё]      ← choose the text to publish
    [❌ Отменить]
    [✅ Опубликовать]

Works on two record kinds:
    kind 'm' = manual pending post (pending_posts, keyed by user_id)
    kind 'a' = channel approval   (pending_approvals, keyed by approval id)
callback_data: pv:{kind}:{id}:{action}  where action ∈ {o,t,c,x,p}
"""
import logging

from aiogram import Router, types, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

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


async def _delete(storage: Storage, kind: str, record_id: int) -> None:
    if kind == "a":
        await storage.delete_approval(record_id)
    else:
        await storage.delete_pending_post(record_id)


# ── Rendering ──────────────────────────────────────────────


def _src_btn(label: str, kind: str, rid: int, action: str, active: bool) -> InlineKeyboardButton:
    text = f"✅ {label}" if active else label
    style = "success" if active else None
    data = f"pv:{kind}:{rid}:{action}"
    if style:
        return InlineKeyboardButton(text=text, callback_data=data, style=style)
    return InlineKeyboardButton(text=text, callback_data=data)


def preview_keyboard(kind: str, rid: int, active_mode: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [
            _src_btn("🌐 Оригинал", kind, rid, "o", active_mode == "original"),
            _src_btn("🔤 Перевод", kind, rid, "t", active_mode == "translated"),
            _src_btn("✏️ Своё", kind, rid, "c", active_mode == "custom"),
        ]
    ]
    # When custom text is active, offer an "Изменить" button to re-edit it.
    if active_mode == "custom":
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
    _, kind, raw_id, action = callback.data.split(":")
    rid = int(raw_id)
    record = await _get_record(storage, kind, rid)

    if record is None or record.user_id != callback.from_user.id:
        await callback.answer("Пост уже обработан или недоступен ❌", show_alert=True)
        return

    if action == "o":
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
    try:
        await callback.message.edit_text(
            preview_text(record, kind),
            reply_markup=preview_keyboard(kind, rid, record.active_mode),
        )
    except Exception as e:
        logger.debug(f"preview refresh no-op: {e}")


async def _start_custom(callback, state, kind, rid, record) -> None:
    await state.set_state(CustomText.waiting)
    # Send ONE reference message with the current text — it (and the user's
    # reply) get deleted after the edit, leaving only the preview message.
    ref = await callback.message.answer(
        f"📋 <b>Текущий текст</b> (скопируйте и отредактируйте):\n\n"
        f"{record.active_text}\n\n"
        f"✏️ Пришлите новый текст. /cancel — оставить текущий."
    )
    await state.update_data(
        kind=kind, rid=rid,
        msg_id=callback.message.message_id,   # the preview message to update
        ref_id=ref.message_id,                 # this reference message to delete
    )


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
        user, record.active_text or record.translated_text, record.photo_file_ids
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
    # Delete the reference message; keep the user's "/cancel" cleanup tidy too.
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

    # Clean up: delete both the reference message and the user's input message
    # so the chat is left with only the preview message.
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

    # Update the original preview message in place.
    if msg_id:
        try:
            await bot.edit_message_text(
                preview_text(record, kind),
                chat_id=message.chat.id,
                message_id=msg_id,
                reply_markup=preview_keyboard(kind, rid, "custom"),
            )
            return
        except Exception:
            pass
    # Fallback: send a fresh preview.
    await message.answer(
        preview_text(record, kind), reply_markup=preview_keyboard(kind, rid, "custom")
    )
