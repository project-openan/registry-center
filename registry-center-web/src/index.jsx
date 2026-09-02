// Copyright (c) 2026 Huawei Technologies Co., Ltd.
// All Rights Reserved.
//
// SPDX-License-Identifier: Apache-2.0
//
//    Licensed under the Apache License, Version 2.0 (the "License"); you may
//    not use this file except in compliance with the License. You may obtain
//    a copy of the License at
//
//         http://www.apache.org/licenses/LICENSE-2.0
//
//    Unless required by applicable law or agreed to in writing, software
//    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
//    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
//    License for the specific language governing permissions and limitations
//    under the License.

/**
 * Portal plugin entry — exports the Registry Center as a pure content
 * component. The Portal shell provides navigation / auth / theme / i18n
 * via PortalContext; this component only renders the agent registry itself.
 *
 * Loaded by the OpenAN Portal as a UMD bundle (local or remote mode).
 */
import { useTranslation } from 'react-i18next';
import { usePortalContext } from '@openan/portal-sdk';
import { ErrorBoundary } from '@/components/common/error_boundary/index.jsx';
import AgentRegistry from '@/components/registry_center/index.jsx';

export default function RegistryCenterPlugin() {
    const { theme, api } = usePortalContext();
    const isDark = theme.isDark;

    return (
        <div className="h-full w-full relative z-10 visible animate-in">
            <ErrorBoundary>
                <AgentRegistry isDark={isDark} api={api} />
            </ErrorBoundary>
        </div>
    );
}
