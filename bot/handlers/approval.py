"""Approval flow for auto-mode channel posts.

When a user has /approve on, channel posts arrive as a preview DM with three
buttons: ✅ Опубликовать / ✏️ Изменить / ❌ Отклонить. This module handles those
callbacks plus the "edit text" FSM step.
"""
import logging

from aiogram import Router, types, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from bot.text_format import format_text
from services.storage import Storage
from services.publisher import Publisher, render_results

router = Router()
logger = logging.getLogger(__name__)


class EditState(StatesGroup):
    waiting_new_text = State()


def _preview_text(translated_text: str, photo_file_ids: list[str]) -> str:
    text = f"🆕 <b>Превью поста:</b>\n\n{translated_text}\n\n"
    if photo_file_ids:
        text += f"🖼️ Изображений: {len(photo_file_ids)} шт.\n\n"
    return text


@router.callback_query(F.data.startswith("apv:"))
async def handle_approval_callback(
    callback: types.CallbackQuery,
    state: FSMContext,
    storage: Storage,
    publisher: Publisher,
    bot: Bot,
) -> None:
    # callback_data format: apv:{id}:{action}
    _, raw_id, action = callback.data.split(":")
    approval_id = int(raw_id)
    approval = await storage.get_approval(approval_id)

    if approval is None or approval.user_id != callback.from_user.id:
        await callback.answer("Пост уже обработан или недоступен ❌", show_alert=True)
        return

    if action == "pub":
        await _publish(callback, bot, storage, publisher, approval)
    elif action == "edit":
        await _start_edit(callback, state, storage, approval_id)
    elif action == "skip":
        await _skip(callback, storage, approval_id)
    else:
        await callback.answer()


async def _publish(callback, bot, storage, publisher: Publisher, approval) -> None:
    await callback.message.edit_text("⏳ Публикую...")
    user = await storage.get_user(approval.user_id)
    if user is None:
        await callback.message.edit_text("❌ Пользователь не найден.")
        await callback.answer()
        return
    results = await publisher.publish_to_all(
        user, approval.translated_text, approval.photo_file_ids
    )
    if any(r.ok for r in results):
        await storage.delete_approval(approval.id)
        await callback.message.edit_text("✅ Готово!\n" + render_results(results))
    else:
        await callback.message.edit_text(
            "❌ Ни один destination не сработал:\n" + render_results(results)
        )
    await callback.answer()


async def _start_edit(callback, state, storage, approval_id) -> None:
    approval = await storage.get_approval(approval_id)
    await state.set_state(EditState.waiting_new_text)
    await state.update_data(approval_id=approval_id)
    # Telegram can't pre-fill the input field, so send the current text as a
    # separate plain message — easy to long-press → Copy → paste → edit.
    if approval:
        await callback.message.answer(
            f"📋 Текущий текст (скопируйте его, отредактируйте и пришлите обратно):\n\n"
            f"{approval.translated_text}"
        )
    await callback.message.answer(
        "✏️ Пришлите новый текст поста.\n"
        "<i>Отправьте /cancel, чтобы оставить текущий без изменений.</i>"
    )
    await callback.answer()


async def _skip(callback, storage, approval_id) -> None:
    await storage.delete_approval(approval_id)
    await callback.message.edit_text("🗑️ Пост отклонён.")
    await callback.answer()


# ── Edit FSM: receive the new text ─────────────────────────

@router.message(EditState.waiting_new_text, F.text)
async def receive_edited_text(message: types.Message, state: FSMContext, storage: Storage) -> None:
    data = await state.get_data()
    approval_id = data.get("approval_id")
    approval = await storage.get_approval(approval_id) if approval_id else None

    if approval is None:
        await state.clear()
        await message.answer("❌ Пост уже недоступен.")
        return

    new_text = format_text(message.text)
    await storage.update_approval_text(approval_id, new_text)
    await state.clear()

    from bot.handlers.channel import approval_keyboard

    await message.answer(
        f"{_preview_text(new_text, approval.photo_file_ids)}Подтвердите публикацию:",
        reply_markup=approval_keyboard(approval_id),
    )


@router.message(EditState.waiting_new_text, F.text.lower() == "/cancel")
async def cancel_edit(message: types.Message, state: FSMContext, storage: Storage) -> None:
    data = await state.get_data()
    approval_id = data.get("approval_id")
    approval = await storage.get_approval(approval_id) if approval_id else None
    await state.clear()

    if approval is None:
        await message.answer("Редактирование отменено.")
        return

    from bot.handlers.channel import approval_keyboard

    await message.answer(
        f"{_preview_text(approval.translated_text, approval.photo_file_ids)}Подтвердите публикацию:",
        reply_markup=approval_keyboard(approval_id),
    )
