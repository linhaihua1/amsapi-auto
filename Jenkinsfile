// ============================================================================
// Jenkins 声明式流水线：amsapi-auto 接口自动化
// ============================================================================
// 使用前置条件：
//   1. Jenkins 安装了以下插件
//        - Allure Jenkins Plugin（渲染 allure-results）
//        - Pipeline（流水线）
//   2. Jenkins 节点已安装 Python 3.7+（推荐 3.10+），且 `python` 可执行
//   3. 可选：节点已安装 allure 命令行工具（若想让本流水线直接产出 HTML 报告）
//
// 典型用法：
//   - 构建时选择 RUN_MODE=smoke  -> 构建后冒烟验证（快，建议接入自动触发）
//   - 构建时选择 RUN_MODE=full   -> 全量回归（可用于每日定时）
//   - 通过 Jenkins 参数或环境变量切换域名，无需修改仓库配置
//
// 阶段顺序（失败即停）：
//   检出代码 -> 准备环境 -> 数据与配置自检 -> 框架单元测试 -> 冒烟/全量 -> 归档报告
//   「框架单元测试」离线运行（约 3 秒），用于确认框架自身没被改坏；
//   若它失败，后续接口测试结果没有参考价值，因此放在接口测试之前执行。
//
// 报告查看：构建完成后，构建页左侧「Allure Report」即可查看
// ============================================================================

pipeline {
    agent any

    parameters {
        choice(name: 'RUN_MODE', choices: ['smoke', 'full'],
               description: '执行模式：smoke=仅冒烟用例（构建后验证）；full=全量回归')
        choice(name: 'TARGET_ENV', choices: ['test', 'uat', 'prod'],
               description: '目标环境标识（写入报告「环境」页，便于区分）')
        string(name: 'BASE_URL', defaultValue: '',
               description: '接口域名。留空则使用仓库 conf.ini 中的 base_url；填写则覆盖（如 http://10.0.0.1:9050）')
        string(name: 'SMOKE_TAGS', defaultValue: 'smoke',
               description: '冒烟标签，多个用逗号分隔（对应用例数据的 tags 字段）')
        booleanParam(name: 'WRITE_BACK', defaultValue: false,
                     description: '是否把执行结果回写数据源（CI 环境建议 false，避免改动仓库文件）')
        string(name: 'TIMEOUT', defaultValue: '30',
               description: '单个请求超时（秒）。内网环境建议 30 以上')
        choice(name: 'DATA_SOURCE', choices: ['excel', 'yaml', 'mysql'],
               description: '用例数据源')
        string(name: 'SYSTEM', defaultValue: 'default',
               description: '系统适配档案名（config/systems/<名>.ini）。' +
                            'default=内置默认，行为与原始版本一致；' +
                            '可选 gov / finance_erp / mall / dataplatform，' +
                            '或自行新增档案。切换被测系统只需改这里，用例数据无需改动')
    }

    options {
        timestamps()                                            // 每行日志带时间戳
        buildDiscarder(logRotator(numToKeepStr: '30'))           // 保留最近 30 次构建
        skipDefaultCheckout(true)                                // 由「检出代码」阶段显式检出
        timeout(time: 60, unit: 'MINUTES')                       // 整体超时保护，避免挂死
        disableConcurrentBuilds()                                // 避免并发写同一份数据文件
    }

    environment {
        // 固定配置放在这里；与构建参数相关的变量在「准备环境」阶段用 script 设置，
        // 避免 environment 块在 params 尚未初始化时求值导致取到空值
        AMSAPI_REPORT_TYPE = 'allure'
        // CI 中默认跳过本地 HTML 渲染（由 Jenkins Allure 插件渲染），缩短构建时长
    }

    stages {
        stage('检出代码') {
            steps {
                checkout scm
                sh 'python --version'
                sh 'python -c "import sys; print(sys.executable)"'
            }
        }

        stage('准备环境') {
            steps {
                script {
                    // 通过 AMSAPI_* 环境变量覆盖配置（优先级高于 conf.ini），无需改动仓库文件
                    env.AMSAPI_ENV = params.TARGET_ENV
                    env.AMSAPI_DATA_SOURCE = params.DATA_SOURCE
                    env.AMSAPI_TIMEOUT = params.TIMEOUT
                    env.AMSAPI_TAGS = params.SMOKE_TAGS
                    env.AMSAPI_WRITE_BACK = params.WRITE_BACK ? 'true' : 'false'
                    // 系统适配档案：决定「成功怎么判、令牌怎么带、报文怎么编解码」
                    env.AMSAPI_SYSTEM = params.SYSTEM

                    // BASE_URL 仅在填写时注入，留空则沿用仓库配置
                    if (params.BASE_URL != null && params.BASE_URL.trim() != '') {
                        env.AMSAPI_BASE_URL = params.BASE_URL.trim()
                    }

                    def domain = env.AMSAPI_BASE_URL ?: '使用仓库 conf.ini 配置'
                    echo "执行模式=${params.RUN_MODE} 目标环境=${params.TARGET_ENV} " +
                         "系统档案=${params.SYSTEM} 结果回写=${env.AMSAPI_WRITE_BACK} 域名=${domain}"
                }
                sh 'pip install -r requirements.txt'
            }
        }

        stage('数据与配置自检') {
            steps {
                // 只收集不执行，快速确认用例数据可被正确读取（该命令完全只读）
                sh 'python main.py --collect-only'
            }
        }

        stage('框架单元测试') {
            steps {
                // 离线自检：验证框架自身代码（参数化 / 关联 / Excel 读写 / 断言等）未被改坏。
                // 不依赖被测环境，秒级完成；失败时后续接口测试无意义，故放在最前面执行。
                sh 'python -m pytest tests -q'
            }
        }

        stage('冒烟测试') {
            when { expression { params.RUN_MODE == 'smoke' } }
            steps {
                sh 'python main.py --smoke --report allure'
            }
        }

        stage('全量回归') {
            when { expression { params.RUN_MODE == 'full' } }
            steps {
                sh 'python main.py --report allure'
            }
        }
    }

    post {
        always {
            // 归档日志与 HTML 报告，便于事后追溯
            archiveArtifacts artifacts: 'log/*.log, report/report.html',
                             allowEmptyArchive: true,
                             fingerprint: true

            // 用 Allure 插件渲染报告（基于 report/allure-results）
            allure includeProperties: true, jdk: '', results: [[path: 'report/allure-results']]
        }

        success {
            echo "构建成功：${params.TARGET_ENV} / ${params.RUN_MODE}"
        }

        failure {
            echo "构建失败：${params.TARGET_ENV} / ${params.RUN_MODE}，请查看 Allure 报告与日志"
            // 如需通知，取消注释并配置：
            // emailext(
            //     subject: "[失败] ${env.JOB_NAME} #${env.BUILD_NUMBER}",
            //     body: "接口自动化测试未通过，详情见 ${env.BUILD_URL}allure",
            //     to: 'team@example.com'
            // )
        }
    }
}
