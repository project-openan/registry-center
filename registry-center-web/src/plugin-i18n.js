// Copyright (c) 2026 Huawei Technologies Co., Ltd.
// SPDX-License-Identifier: Apache-2.0
import en from './locales/en.json';
import zh from './locales/zh.json';

export const PLUGIN_I18N_NAMESPACE = 'registry-center';

export function registerPluginI18n(i18n) {
    if (!i18n || typeof i18n.addResourceBundle !== 'function') return false;
    for (const [language, bundle] of Object.entries({en, zh})) {
        i18n.addResourceBundle(language, PLUGIN_I18N_NAMESPACE, bundle, true, false);
    }
    return true;
}
