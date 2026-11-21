(() => {
    'use strict';
    const section = document.getElementById('shipping-address-map');
    if (!section) return;
    const button = section.querySelector('[data-map-show]');
    const hideButton = section.querySelector('[data-map-hide]');
    const canvas = section.querySelector('[data-map-canvas]');
    const status = section.querySelector('[data-map-status]');
    const label = 'Vị trí ước tính của địa chỉ nhận hàng';
    const caption = 'Vị trí ước tính từ địa chỉ, không phải theo dõi đơn vị vận chuyển';
    let map = null;
    let pending = false;
    if (!window.L) {
        status.textContent = 'Chưa tải được thư viện bản đồ. Vui lòng tải lại trang.';
        return;
    }
    button.disabled = false;

    function clearMap() {
        if (map) map.remove();
        map = null;
        canvas.hidden = true;
        hideButton.hidden = true;
        button.hidden = false;
        button.setAttribute('aria-expanded', 'false');
    }

    hideButton.addEventListener('click', () => {
        clearMap();
        status.textContent = 'Bản đồ đã ẩn. Không tải thêm ô bản đồ cho đến khi bạn chọn hiển thị lại.';
        button.focus();
    });

    button.addEventListener('click', async () => {
        if (pending || map) return;
        const leaflet = window.L;
        if (!leaflet) {
            status.textContent = 'Chưa tải được thư viện bản đồ. Vui lòng tải lại trang.';
            return;
        }
        // Accept only this page's canonical, owner-scoped endpoint. Never fetch
        // a provider URL, query string or redirect from response data.
        const endpoint = new URL(section.dataset.geocodeUrl, window.location.origin);
        if (endpoint.origin !== window.location.origin ||
            !/^\/shipping\/geocode\/[1-9][0-9]*$/.test(endpoint.pathname) || endpoint.search || endpoint.hash) {
            status.textContent = 'Chưa cấu hình được bản đồ cho đơn hàng này.';
            return;
        }
        pending = true;
        button.disabled = true;
        section.setAttribute('aria-busy', 'true');
        status.textContent = 'Đang tìm vị trí theo địa chỉ đã lưu…';
        const controller = new AbortController();
        const timeout = window.setTimeout(() => controller.abort(), 12000);
        try {
            const response = await fetch(endpoint.href, {
                method: 'GET',
                headers: { Accept: 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
                credentials: 'same-origin',
                cache: 'no-store',
                redirect: 'error',
                signal: controller.signal
            });
            const data = await response.json();
            if (!response.ok || data.success !== true) {
                const messages = {
                    401: 'Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại để xem vị trí.',
                    403: 'Bạn không có quyền xem vị trí của đơn hàng này.',
                    404: 'Chưa tìm thấy vị trí phù hợp hoặc đơn hàng không khả dụng.',
                    422: 'Địa chỉ đã lưu chưa đủ thông tin để xác định vị trí.',
                    429: 'Dịch vụ bản đồ đang giới hạn lượt xem. Vui lòng thử lại sau.',
                    503: 'Dịch vụ bản đồ tạm thời không khả dụng hoặc tra cứu bên ngoài đang tắt. Vui lòng thử lại sau.'
                };
                throw new Error(messages[response.status] || 'Không thể xem vị trí theo địa chỉ. Vui lòng thử lại sau.');
            }
            if (data.approximate !== true || data.source !== 'shipping_address' ||
                typeof data.lat !== 'number' || typeof data.lon !== 'number' ||
                !Number.isFinite(data.lat) || !Number.isFinite(data.lon) ||
                Math.abs(data.lat) > 90 || Math.abs(data.lon) > 180) {
                throw new Error('Chưa nhận được tọa độ hợp lệ. Không thể hiển thị bản đồ.');
            }
            canvas.hidden = false;
            map = leaflet.map(canvas, {
                scrollWheelZoom: false, zoomAnimation: false, fadeAnimation: false,
                markerZoomAnimation: false, maxZoom: 18, minZoom: 2
            }).setView([data.lat, data.lon], 15);
            const tiles = leaflet.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
                attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" rel="external">OpenStreetMap</a> contributors',
                maxZoom: 18, noWrap: true, keepBuffer: 0, updateWhenIdle: true,
                updateWhenZooming: false, detectRetina: false,
                // OSM requires a Referer. Origin sends neither order ID nor
                // shipping address, and overrides the site's same-origin policy
                // for these opted-in images only. Browser tile caching is kept.
                referrerPolicy: 'origin'
            });
            tiles.on('tileerror', () => {
                status.textContent = 'Đã xác định vị trí ước tính nhưng không tải được nền bản đồ. Đây không phải bản đồ đang hoạt động trực tuyến.';
            });
            tiles.addTo(map);
            const popup = document.createElement('p');
            popup.textContent = caption;
            const marker = leaflet.marker([data.lat, data.lon], { title: label, alt: label, keyboard: true });
            marker.bindPopup(popup).addTo(map);
            const zoom = canvas.querySelector('.leaflet-control-zoom');
            zoom?.querySelector('.leaflet-control-zoom-in')?.setAttribute('aria-label', 'Phóng to bản đồ');
            zoom?.querySelector('.leaflet-control-zoom-out')?.setAttribute('aria-label', 'Thu nhỏ bản đồ');
            map.invalidateSize();
            canvas.focus({ preventScroll: true });
            button.hidden = true;
            hideButton.hidden = false;
            button.setAttribute('aria-expanded', 'true');
            status.textContent = caption;
        } catch (error) {
            clearMap();
            status.textContent = error.name === 'AbortError'
                ? 'Dịch vụ bản đồ phản hồi quá chậm. Vui lòng thử lại sau.'
                : error.message || 'Không tải được bản đồ. Vui lòng thử lại sau.';
        } finally {
            window.clearTimeout(timeout);
            pending = false;
            button.disabled = false;
            section.setAttribute('aria-busy', 'false');
        }
    });
    window.addEventListener('pagehide', clearMap);
})();
