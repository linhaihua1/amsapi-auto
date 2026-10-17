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
//   检出代码 -> 准备环境 -> 静态检查 -> 环境预检 -> 数据与配置自检
//   -> 框架单元测试（含覆盖率门槛） -> 冒烟/全量 -> 归档报告
//
// 各道门的用意（越靠前越便宜，越早失败越省钱）：
//   静态检查     秒级，拦语法 / 未使用导入 / 明显笔误
//   环境预检     十几秒，拦「依赖缺失、配置非法、档案不存在、域名不可达」
//                —— 否则这些问题会表现为几十条用例失败，排查成本完全不同
//   单元测试     离线，确认框架自身没被改坏 + 覆盖率不低于门槛
//   冒烟/全量    真正打接口；若前四道门都没红，这里的失败才真的是业务问题
//
// 报告查看：构建完成后，构建页左侧「Allure Report」即可查看
// ============================================================================

// ---------------------------------------------------------------------------
// 辅助函数：按「插件是否已安装」决定是否追加参数
// ---------------------------------------------------------------------------
// 为什么要在运行时探测而不是直接写死参数：
//     并行（xdist）与重试（rerunfailures）属于增强能力，节点上未必安装。
//     写死会让「没装插件的节点」直接构建失败，而失败原因与测试质量无关。
//     探测后降级，既保住流水线可用性，又不会静默假装用过（会打印跳过原因）。
String pluginArgs(boolean needRetries, String retries, boolean needParallel, String parallel) {
    def args = []
    if (needRetries) {
        def hasRerun = sh(script: 'python -c "import pytest_rerunfailures"',
                          returnStatus: true) == 0
        if (hasRerun) {
            args << "--reruns=${retries} --reruns-delay=2"
        } else {
            echo "[跳过] 未安装 pytest-rerunfailures，本次不启用失败重试"
        }
    }
    if (needParallel) {
        def hasXdist = sh(script: 'python -c "import xdist"', returnStatus: true) == 0
        if (hasXdist) {
            args << "-n ${parallel}"
        } else {
            echo "[跳过] 未安装 pytest-xdist，本次不启用并行执行"
        }
    }
    return args.join(' ')
}

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
        string(name: 'COVERAGE_MIN', defaultValue: '80',
               description: '框架自测覆盖率下限（%）。低于该值构建失败，用于防止「改了框架但没补单测」')
        string(name: 'RETRIES', defaultValue: '0',
               description: '失败用例重试次数（需 pytest-rerunfailures）。建议 1：网络抖动不至于让整轮红掉')
        string(name: 'PARALLEL', defaultValue: '1',
               description: '并行进程数（需 pytest-xdist）。1 = 串行执行')
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
                sh '''
                    set -e
                    pip install --disable-pip-version-check -r requirements.txt
                    pip install --disable-pip-version-check -r requirements-dev.txt \
                      || echo "[警告] 开发依赖安装失败：静态检查 / 覆盖率 / 并行 / 重试将自动降级，继续执行"
                '''
            }
        }

        stage('静态检查') {
            steps {
                script {
                    // 秒级反馈的门：只拦语法级 / 明显笔误级问题，不做风格洁癖
                    def hasFlake8 = sh(script: 'python -c "import flake8"',
                                       returnStatus: true) == 0
                    if (hasFlake8) {
                        sh 'python -m flake8 .'
                    } else {
                        echo "[跳过] 未安装 flake8（pip install -r requirements-dev.txt）"
                    }
                }
            }
        }

        stage('环境预检') {
            steps {
                // 把「依赖缺失 / 配置非法 / 档案不存在 / 用例数据不可读 / 域名不可达」
                // 在跑用例之前一次性确认掉，避免环境问题被误解成一堆业务用例失败。
                // 阻断性问题（错误）返回非 0；警告（如可选依赖未装）只提示不阻断。
                // 若希望「有警告也失败」，把下面改成 python tools/preflight.py --strict
                sh 'python tools/preflight.py'
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
                script {
                    // 离线自检：验证框架自身代码（参数化 / 关联 / Excel 读写 / 断言 / 脱敏 …）
                    // 未被改坏，并守住覆盖率下限 —— 改了框架却不补单测，在这里就被拦住。
                    // 不依赖被测环境，秒级完成；失败时后续接口测试无意义，故放在最前面执行。
                    // -o addopts="" 去掉 pytest.ini 里的 -vs，避免 CI 日志被逐条用例刷屏。
                    def hasCov = sh(script: 'python -c "import pytest_cov"',
                                    returnStatus: true) == 0
                    if (hasCov) {
                        sh "python -m pytest tests -o addopts='' -q " +
                           "--cov --cov-report=term-missing:skip-covered " +
                           "--cov-report=xml:report/coverage.xml " +
                           "--cov-fail-under=${params.COVERAGE_MIN}"
                    } else {
                        echo "[降级] 未安装 pytest-cov，本次仅执行单元测试、不校验覆盖率"
                        sh "python -m pytest tests -o addopts='' -q"
                    }
                }
            }
        }

        stage('冒烟测试') {
            when { expression { params.RUN_MODE == 'smoke' } }
            steps {
                script {
                    def extra = pluginArgs(params.RETRIES?.trim() && params.RETRIES != '0',
                                           params.RETRIES,
                                           params.PARALLEL?.trim() && params.PARALLEL != '1',
                                           params.PARALLEL)
                    sh "python main.py --smoke --report allure ${extra}"
                }
            }
        }

        stage('全量回归') {
            when { expression { params.RUN_MODE == 'full' } }
            steps {
                script {
                    def extra = pluginArgs(params.RETRIES?.trim() && params.RETRIES != '0',
                                           params.RETRIES,
                                           params.PARALLEL?.trim() && params.PARALLEL != '1',
                                           params.PARALLEL)
                    sh "python main.py --report allure ${extra}"
                }
            }
        }
    }

    post {
        always {
            // 归档日志与各类报告，便于事后追溯与复盘。
            // 日志与 Allure 报告中的口令 / 令牌已由框架脱敏（conf.ini [log] mask_sensitive），
            // 因此归档制品可以安全地在团队内共享。
            archiveArtifacts artifacts: 'log/*.log, report/report.html, ' +
                                        'report/coverage.xml, report/unit-coverage/**',
                             allowEmptyArchive: true,
                             fingerprint: true

            // 用 Allure 插件渲染报告（基于 report/allure-results）。
            // 报告「环境」页会带上构建号 / git 提交 / 分支 / 依赖版本（见 common/metadata.py），
            // 单独把报告转发出去也能确认它对应哪次构建、哪次提交。
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
