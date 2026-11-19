import { copyFile, mkdir, readdir } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const files = [
    ['bootstrap/dist/css/bootstrap.min.css', 'bootstrap/bootstrap.min.css'],
    ['bootstrap/dist/js/bootstrap.bundle.min.js', 'bootstrap/bootstrap.bundle.min.js'],
    ['jquery/dist/jquery.min.js', 'jquery/jquery.min.js'],
    ['chart.js/dist/chart.umd.js', 'chart/chart.umd.js'],
    ['socket.io-client/dist/socket.io.min.js', 'socketio/socket.io.min.js'],
    ['@fortawesome/fontawesome-free/css/all.min.css', 'fontawesome/css/all.min.css'],
    ['@fontsource/inter/index.css', 'inter/inter.css'],
];
for (const [source, destination] of files) {
    const target = resolve(root, 'app/static/vendor', destination);
    await mkdir(dirname(target), { recursive: true });
    await copyFile(resolve(root, 'node_modules', source), target);
}
for (const [source, destination] of [
    ['@fortawesome/fontawesome-free/webfonts', 'fontawesome/webfonts'],
    ['@fontsource/inter/files', 'inter/files'],
]) {
    const directory = resolve(root, 'app/static/vendor', destination);
    await mkdir(directory, { recursive: true });
    for (const filename of await readdir(resolve(root, 'node_modules', source))) {
        if (filename.endsWith('.woff2')) await copyFile(resolve(root, 'node_modules', source, filename), resolve(directory, filename));
    }
}
console.log('Copied pinned browser libraries and Vietnamese-capable Inter fonts.');
