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
from services.linkedin import LinkedInClient

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
    linkedin_client: LinkedInClient,
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
        await _publish(callback, bot, storage, linkedin_client, approval)
    elif action == "edit":
        await _start_edit(callback, state, storage, approval_id)
    elif action == "skip":
        await _skip(callback, storage, approval_id)
    else:
        await callback.answer()


async def _publish(callback, bot, storage, linkedin_client, approval) -> None:
    await callback.message.edit_text("⏳ Публикую в LinkedIn...")
    try:
        # Inline helper to upload images + create post (mirrors channel.py).
        image_asset_urns: list[str] = []
        for file_id in approval.photo_file_ids:
            try:
                file = await bot.get_file(file_id)
                image_bytes = await bot.download_file(file.file_path)
                image_data = image_bytes.read()
                asset_urn = await linkedin_client.upload_image_full(
                    (await storage.get_user(approval.user_id)).linkedin_access_token,
                    (await storage.get_user(approval.user_id)).linkedin_person_urn,
                    image_data,
                )
                image_asset_urns.append(asset_urn)
            except Exception as e:
                logger.error(f"Image upload failed: {e}")

        user = await storage.get_user(approval.user_id)
        await linkedin_client.create_post(
            user.linkedin_access_token, user.linkedin_person_urn,
            approval.translated_text, image_asset_urns or None,
        )
        await storage.delete_approval(approval.id)
        await callback.message.edit_text("✅ Опубликован в LinkedIn!")
    except Exception as e:
        logger.error(f"Approval publish failed: {e}")
        await callback.message.edit_text(
            f"❌ Ошибка публикации: {e}\n\nПопробуйте переподключить: /auth"
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
