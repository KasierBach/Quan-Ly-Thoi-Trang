(() => {
    'use strict';

    if (!document.body.classList.contains('admin-page')) return;

    const root = document.documentElement;
    const legendGenerators = new WeakMap();

    function updateCharts() {
        const ChartAPI = window.Chart;
        if (typeof ChartAPI?.getChart !== 'function') return;

        const styles = getComputedStyle(document.body);
        const color = name => styles.getPropertyValue(name).trim();
        const text = color('--admin-text');
        const muted = color('--admin-muted');
        const surface = color('--admin-surface');
        const border = color('--admin-border');

        document.querySelectorAll('.admin-page > .main-content canvas').forEach(canvas => {
            const chart = ChartAPI.getChart(canvas);
            if (!chart) return;

            // Only presentation options change; data, callbacks and chart types stay intact.
            const options = chart.options;
            options.color = text;
            const plugins = options.plugins || (options.plugins = {});
            if (plugins.legend !== false) {
                const legend = plugins.legend || (plugins.legend = {});
                const labels = legend.labels || (legend.labels = {});
                labels.color = text;
                if (typeof labels.generateLabels === 'function') {
                    if (!legendGenerators.has(chart)) {
                        const generate = labels.generateLabels;
                        const themed = function (...args) {
                            return generate.apply(this, args).map(label => ({ ...label, fontColor: chart.options.color }));
                        };
                        legendGenerators.set(chart, themed);
                    }
                    // Reports provide custom labels; retain their values, swatches and hidden state.
                    labels.generateLabels = legendGenerators.get(chart);
                }
                if (legend.title) legend.title.color = text;
            }
            if (plugins.tooltip !== false) {
                const tooltip = plugins.tooltip || (plugins.tooltip = {});
                Object.assign(tooltip, {
                    backgroundColor: surface,
                    titleColor: text,
                    bodyColor: text,
                    footerColor: muted,
                    borderColor: border,
                    borderWidth: 1
                });
            }
            if (plugins.title) plugins.title.color = text;
            if (plugins.subtitle) plugins.subtitle.color = muted;
            Object.values(options.scales || {}).forEach(scale => {
                if (scale.ticks !== false) {
                    const ticks = scale.ticks || (scale.ticks = {});
                    ticks.color = muted;
                }
                if (scale.grid !== false) {
                    const grid = scale.grid || (scale.grid = {});
                    grid.color = border;
                    grid.tickColor = border;
                }
                if (scale.border !== false) {
                    const axisBorder = scale.border || (scale.border = {});
                    axisBorder.color = border;
                }
                if (scale.title) scale.title.color = text;
                if (scale.pointLabels) scale.pointLabels.color = muted;
                if (scale.angleLines) scale.angleLines.color = border;
            });
            chart.update('none');
        });
    }

    let scheduled = false;
    function scheduleUpdate() {
        if (scheduled) return;
        scheduled = true;
        requestAnimationFrame(() => {
            scheduled = false;
            updateCharts();
        });
    }

    new MutationObserver(scheduleUpdate).observe(root, {
        attributes: true,
        attributeFilter: ['data-bs-theme']
    });
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', scheduleUpdate, { once: true });
    } else {
        scheduleUpdate();
    }
    // Covers delayed Chart scripts without registering global Chart defaults/plugins.
    window.addEventListener('load', scheduleUpdate, { once: true });
})();
