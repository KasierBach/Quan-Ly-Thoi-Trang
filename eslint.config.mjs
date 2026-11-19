import js from '@eslint/js';
import globals from 'globals';

export default [
    { ignores: ['node_modules/**', 'app/static/vendor/**', 'artifacts/**'] },
    js.configs.recommended,
    {
        files: ['app/static/js/**/*.js'],
        languageOptions: { globals: { ...globals.browser, bootstrap: 'readonly', Chart: 'readonly', io: 'readonly', $: 'readonly' } },
        rules: { 'no-unused-vars': ['error', { argsIgnorePattern: '^_', caughtErrorsIgnorePattern: '^_', varsIgnorePattern: '^_' }] }
    },
    { files: ['tools/*.mjs', 'tests/js/*.mjs'], languageOptions: { globals: globals.node } },
];
