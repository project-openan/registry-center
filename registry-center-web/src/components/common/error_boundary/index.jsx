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

import { Component } from 'react'
import { withTranslation } from 'react-i18next'
import { AlertTriangle } from 'lucide-react'

class ErrorBoundaryBase extends Component {
    constructor(props) {
        super(props)
        this.state = { hasError: false }
    }

    static getDerivedStateFromError() {
        return { hasError: true }
    }

    componentDidCatch(error, info) {
        console.error('ErrorBoundary caught:', error, info)
    }

    handleReset = () => {
        this.setState({ hasError: false })
    }

    render() {
        const { t } = this.props
        if (this.state.hasError) {
            return (
                <div className="flex flex-col items-center justify-center h-full text-center px-6">
                    <div className="p-5 bg-red-50 dark:bg-red-500/10 text-red-500 rounded-3xl mb-6 shadow-lg">
                        <AlertTriangle size={40} />
                    </div>
                    <h2 className="text-2xl font-black text-zinc-900 dark:text-white mb-2">
                        {t('error_boundary.title')}
                    </h2>
                    <p className="text-zinc-500 dark:text-zinc-400 mb-6 max-w-md">
                        {t('error_boundary.subtitle')}
                    </p>
                    <button
                        onClick={this.handleReset}
                        className="px-6 py-3 rounded-2xl bg-blue-500 hover:bg-blue-600 text-white font-bold shadow-lg hover:shadow-xl transition-all duration-300 hover:-translate-y-0.5"
                    >
                        {t('error_boundary.reset')}
                    </button>
                </div>
            )
        }
        return this.props.children
    }
}

export const ErrorBoundary = withTranslation()(ErrorBoundaryBase)
export default ErrorBoundary
