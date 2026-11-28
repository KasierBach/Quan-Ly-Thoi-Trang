(() => {
    const select = document.getElementById('guide-size');
    const values = JSON.parse(document.getElementById('size-guide-values').textContent);
    select.addEventListener('change', () => {
        const row = values.find(item => String(item.sizeid) === select.value);
        for (const field of ['chest', 'waist', 'hips']) {
            document.getElementById('guide-' + field).value = row?.[field] ?? '';
        }
    });
})();
