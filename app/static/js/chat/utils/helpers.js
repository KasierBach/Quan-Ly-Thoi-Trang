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
        if (window.chatApp && window.chatApp.pickingForSetting === 'emoji') {
            window.chatApp.handleDefaultEmojiChange(emoji);
            window.chatApp.pickingForSetting = null;
            picker.classList.remove('active');
            return;
        }
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


export function renderStickers(gridId) {
    // Using reliable Twemoji CDN
    const stickers = [
        'https://cdnjs.cloudflare.com/ajax/libs/twemoji/14.0.2/72x72/1f600.png', // Grinning
        'https://cdnjs.cloudflare.com/ajax/libs/twemoji/14.0.2/72x72/1f60d.png', // Heart Eyes
        'https://cdnjs.cloudflare.com/ajax/libs/twemoji/14.0.2/72x72/1f602.png', // Joy
        'https://cdnjs.cloudflare.com/ajax/libs/twemoji/14.0.2/72x72/1f60e.png', // Cool
        'https://cdnjs.cloudflare.com/ajax/libs/twemoji/14.0.2/72x72/1f973.png', // Party
        'https://cdnjs.cloudflare.com/ajax/libs/twemoji/14.0.2/72x72/1f62d.png', // Loudly Crying
        'https://cdnjs.cloudflare.com/ajax/libs/twemoji/14.0.2/72x72/1f44d.png', // Thumbs Up
        'https://cdnjs.cloudflare.com/ajax/libs/twemoji/14.0.2/72x72/1f44b.png', // Waving Hand
        'https://cdnjs.cloudflare.com/ajax/libs/twemoji/14.0.2/72x72/1f923.png'  // Rolling on Floor Laughing
    ];
    const grid = document.getElementById(gridId);
    if (grid) {
        grid.innerHTML = stickers.map(s => `<div class="sticker-item" onclick="window.chatApp.sendSticker('${s}')"><img src="${s}" style="width: 100%; height: auto; min-height: 50px;"></div>`).join('');
    }
}

export function renderGifs(gridId) {
    const gifs = [
        'https://media.giphy.com/media/nXxOjZ9xEQi1W/giphy.gif', // Success Kid
        'https://media.giphy.com/media/10ECejNtM1GyRy/giphy.gif', // Doge
        'https://media.giphy.com/media/GeimqsH0TLDt4tScGw/giphy.gif', // Cat Vibe
        'https://media.giphy.com/media/l0HlCqV35hdEg2LSM/giphy.gif', // Original reliable one
        'https://media.giphy.com/media/3o7TKSjRrfIPjeiVyM/giphy.gif',
        'https://media.giphy.com/media/26AHONQ79FdWZhAI0/giphy.gif'
    ];
    const grid = document.getElementById(gridId);
    if (grid) {
        grid.innerHTML = gifs.map(g => `<div class="sticker-item" onclick="window.chatApp.sendSticker('${g}')"><img src="${g}" style="width: 100%; height: auto; border-radius: 4px; min-height: 50px;"></div>`).join('');
    }
}
