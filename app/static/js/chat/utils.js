/**
 * Chat Utilities
 * Handles emojis, stickers, and helper functions.
 */

export function initEmojiPicker() {
    const emojiList = [
        '😀', '😃', '😄', '😁', '😆', '😅', '🤣', '😂', '🙂', '🙃', '😉', '😊', '😇',
        '🥰', '😍', '🤩', '😘', '😗', '😙', '😚', '😋', '😛', '😜', '🤪', '😝', '🤑',
        '🤗', '🤭', '🤫', '🤔', '🤐', '🤨', '😐', '😑', '😶', '😏', '😒', '🙄', '😬',
        '🤥', '😌', '😔', '😪', '🤤', '😴', '😷', '🤒', '🤕', '🤢', '🤮', '🤧', '🥵', '🥶', '🥴', '😵', '🤯', '🤠', '🥳',
        '😎', '🤓', '🧐', '😕', '😟', '🙁', '😮', '😯', '😲', '😳', '🥺', '😦', '😧', '😨',
        '😰', '😥', '😢', '😭', '😱', '😖', '😣', '😞', '😓', '😩', '😫', '🥱', '😤',
        '😡', '😠', '🤬', '😈', '👿', '💀', '☠️', '💩', '🤡', '👹', '👺', '👻', '👽', '👾',
        '🤖', '😺', '😸', '😹', '😻', '😼', '😽', '🙀', '😿', '😾', '👋', '🤚', '🖐️',
        '✋', '🖖', '👌', '🤏', '✌️', '🤞', '🤟', '🤘', '🤙', '👈', '👉', '👆', '🖕',
        '👇', '☝️', '👍', '👎', '✊', '👊', '🤛', '🤜', '👏', '🙌', '👐', '🤲', '🤝',
        '🙏', '✍️', '💅', '🤳', '💪', '🦵', '🦶', '👂', '🦻', '👃', '🧠', '🫀', '🫁',
        '🦷', '🦴', '👀', '👁️', '👅', '👄', '💋', '🩸', '💘', '💝', '💖', '💗', '💓',
        '💞', '💕', '💟', '❣️', '💔', '❤️', '🧡', '💛', '💚', '💙', '💜', '🤎', '🖤',
        '🤍', '💯', '💢', '💥', '💫', '💦', '💨', '🕳️', '💣', '💬', '👁️‍🗨️', '🗨️',
        '🗯️', '💭', '💤'
    ];

    const grid = document.getElementById('emojiGrid');
    const picker = document.getElementById('emojiPicker');
    let hoveredEmoji = null;
    let isPickerHovered = false;

    window.getHoveredEmoji = () => {
        if (!picker || !picker.classList.contains('active')) return null;
        return hoveredEmoji || isPickerHovered;
    };

    if (picker) {
        picker.onmouseenter = () => isPickerHovered = true;
        picker.onmouseleave = () => isPickerHovered = false;
    }

    if (!grid) return;

    grid.innerHTML = emojiList.map(e => `<div class="emoji-item" data-emoji="${e}">${e}</div>`).join('');

    grid.querySelectorAll('.emoji-item').forEach(item => {
        item.onclick = (e) => {
            e.stopPropagation();
            insertEmoji(item.dataset.emoji);
        };
        item.onmouseenter = () => {
            hoveredEmoji = item.dataset.emoji;
            isPickerHovered = true;
        };
        item.onmouseleave = () => hoveredEmoji = null;
    });

    function insertEmoji(emoji) {
        const input = document.getElementById('messageInput');
        if (input) {
            input.value += emoji;
            input.focus();
            input.dispatchEvent(new Event('input'));
        }
    }

    window.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && hoveredEmoji && picker && picker.classList.contains('active')) {
            e.preventDefault();
            insertEmoji(hoveredEmoji);
        }
    });
}

export function initStickerPicker() {
    const stickers = [
        'https://th.bing.com/th/id/OIP.Xy9vOQ_uG8-G_y-zX8-5hgHaHa?pid=ImgDet&rs=1',
        'https://th.bing.com/th/id/OIP.Ue-D-T6K9QyLdG4H6zR8ngHaHa?pid=ImgDet&rs=1',
        'https://th.bing.com/th/id/OIP.1-_6S_G8M-K9_G4H6zR8ngHaHa?pid=ImgDet&rs=1'
    ];
    const grid = document.getElementById('stickerGrid');
    if (grid) {
        grid.innerHTML = stickers.map(s => `<div class="sticker-item" onclick="window.chatApp.sendSticker('${s}')"><img src="${s}"></div>`).join('');
    }
}
