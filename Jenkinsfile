pipeline {
    agent any

    environment {
        PROJETO        = 'keahubinnovation'
        STACK_NAME     = 'keahubinnovation'
        DEPLOY_PATH    = '/var/jenkins_home/apps/keahubinnovation'
        GIT_REPO       = 'https://github.com/kealabs-ai/keahubinnovation.git'
        GIT_BRANCH     = 'master'
        DOCKER         = '/var/jenkins_home/docker'
        DOCKER_COMPOSE = '/var/jenkins_home/docker-compose'
        JWT_EXPIRY_HOURS = '8'

        // Credenciais injetadas pelo Jenkins (configuradas em Manage Jenkins > Environment)
        DB_HOST           = credentials('DB_HOST')
        DB_PORT           = credentials('DB_PORT')
        DB_NAME           = credentials('DB_NAME')
        DB_USER           = credentials('DB_USER')
        DB_PASSWORD       = credentials('DB_PASSWORD')
        JWT_SECRET        = credentials('JWT_SECRET')
        GEMINI_API_KEY    = credentials('GEMINI_API_KEY')
        OPENAI_API_KEY    = credentials('OPENAI_API_KEY')
        GROQ_API_KEY      = credentials('GROQ_API_KEY')
        ANTHROPIC_API_KEY = credentials('ANTHROPIC_API_KEY')
    }

    stages {

        // ── 1. CHECKOUT ───────────────────────────────────────────────────
        stage('Checkout') {
            steps {
                checkout scm
            }
        }

        // ── 2. PREPARAR AMBIENTE ──────────────────────────────────────────
        stage('Prepare') {
            steps {
                sh '''
                    set -e
                    mkdir -p $DEPLOY_PATH
                    cd $DEPLOY_PATH

                    if [ -d ".git" ]; then
                        git fetch origin
                        git reset --hard origin/$GIT_BRANCH
                    else
                        git clone -b $GIT_BRANCH $GIT_REPO .
                    fi

                    # Gera .env a partir das credenciais do Jenkins
                    cat > $DEPLOY_PATH/.env <<EOF
DB_HOST=${DB_HOST}
DB_PORT=${DB_PORT}
DB_NAME=${DB_NAME}
DB_USER=${DB_USER}
DB_PASSWORD=${DB_PASSWORD}
JWT_SECRET=${JWT_SECRET}
JWT_EXPIRY_HOURS=${JWT_EXPIRY_HOURS}
GEMINI_API_KEY=${GEMINI_API_KEY}
OPENAI_API_KEY=${OPENAI_API_KEY}
GROQ_API_KEY=${GROQ_API_KEY}
ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
EOF
                    echo "  ✔ .env gerado"
                '''
            }
        }

        // ── 3. COPIAR database.py PARA CADA SERVIÇO ───────────────────────
        stage('Sync database.py') {
            steps {
                sh '''
                    set -e
                    cd $DEPLOY_PATH
                    for service in services/*/; do
                        cp services/database.py "$service"
                        echo "  ✔ database.py → $service"
                    done
                '''
            }
        }

        // ── 5. GARANTIR DOCKER BUILDX ─────────────────────────────────────
        stage('Ensure Buildx') {
            steps {
                sh '''
                    BUILDX_PATH="/var/jenkins_home/.docker/cli-plugins/docker-buildx"
                    if [ ! -f "$BUILDX_PATH" ]; then
                        echo "Instalando docker-buildx..."
                        mkdir -p /var/jenkins_home/.docker/cli-plugins
                        curl -fsSL "https://github.com/docker/buildx/releases/download/v0.17.1/buildx-v0.17.1.linux-amd64" \
                             -o "$BUILDX_PATH"
                        chmod +x "$BUILDX_PATH"
                        echo "  ✔ buildx instalado"
                    else
                        echo "  ✔ buildx já presente"
                    fi
                '''
            }
        }

        // ── 6. BUILD DAS IMAGENS ──────────────────────────────────────────
        stage('Build Images') {
            steps {
                sh '''
                    set -e
                    cd $DEPLOY_PATH

                    echo "▶ Building clients..."
                    $DOCKER build -t $PROJETO/clients:latest \
                        -f services/clients/Dockerfile services/

                    echo "▶ Building quotes..."
                    $DOCKER build -t $PROJETO/quotes:latest \
                        -f services/quotes/Dockerfile services/

                    echo "▶ Building chat..."
                    $DOCKER build -t $PROJETO/chat:latest \
                        -f services/chat/Dockerfile services/

                    echo "▶ Building settings..."
                    $DOCKER build -t $PROJETO/settings:latest \
                        -f services/settings/Dockerfile services/

                    echo "▶ Building agents..."
                    $DOCKER build -t $PROJETO/agents:latest \
                        -f services/agents/Dockerfile services/

                    echo "▶ Building auth..."
                    $DOCKER build -t $PROJETO/auth:latest \
                        -f services/auth/Dockerfile services/

                    echo "▶ Building prospects..."
                    $DOCKER build -t $PROJETO/prospects:latest \
                        -f services/prospects/Dockerfile services/

                    echo "✅ Todas as imagens construídas com sucesso"
                '''
            }
        }

        // ── 7. REMOVER STACK ANTERIOR ─────────────────────────────────────
        stage('Remove Old Stack') {
            steps {
                sh '''
                    set -e
                    echo "▶ Removendo stack anterior: $STACK_NAME"
                    $DOCKER stack rm $STACK_NAME || true
                    sleep 30

                    echo "▶ Aguardando remoção da rede overlay..."
                    for i in $(seq 1 10); do
                        $DOCKER network rm ${STACK_NAME}_${STACK_NAME} 2>/dev/null && break || true
                        sleep 5
                    done
                    echo "  ✔ Stack removida"
                '''
            }
        }

        // ── 8. DEPLOY DA NOVA STACK ───────────────────────────────────────
        stage('Deploy Stack') {
            steps {
                sh '''
                    set -e
                    cd $DEPLOY_PATH

                    echo "▶ Fazendo deploy da stack: $STACK_NAME"
                    env $(cat .env | grep -v '^#' | xargs) \
                        $DOCKER stack deploy \
                        -c docker-compose.yml \
                        $STACK_NAME \
                        --with-registry-auth

                    echo "▶ Status dos serviços:"
                    $DOCKER stack ps $STACK_NAME
                '''
            }
        }

        // ── 9. HEALTH CHECK ───────────────────────────────────────────────
        stage('Health Check') {
            steps {
                sh '''
                    echo "▶ Aguardando containers subirem (60s)..."
                    sleep 60

                    SERVICES="clients quotes chat settings agents auth prospects"
                    FAILED=0

                    for svc in $SERVICES; do
                        CONTAINER=$($DOCKER ps --filter "name=${STACK_NAME}_${svc}-service" --format "{{.ID}}" | head -1)
                        if [ -n "$CONTAINER" ]; then
                            STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
                                --max-time 5 \
                                http://$(docker inspect --format="{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}" $CONTAINER):8000/${svc}/health 2>/dev/null || echo "000")
                            if [ "$STATUS" = "200" ]; then
                                echo "  ✔ $svc → OK"
                            else
                                echo "  ✘ $svc → HTTP $STATUS"
                                FAILED=$((FAILED + 1))
                            fi
                        else
                            echo "  ✘ $svc → container não encontrado"
                            FAILED=$((FAILED + 1))
                        fi
                    done

                    if [ $FAILED -gt 0 ]; then
                        echo "⚠️  $FAILED serviço(s) não responderam ao health check"
                        $DOCKER stack ps $STACK_NAME --no-trunc
                    fi
                '''
            }
        }

    }

    post {
        success {
            echo '✅ Deploy KeaHub Innovation Services realizado com sucesso!'
        }
        failure {
            echo '❌ Falha no deploy KeaHub Innovation Services!'
        }
        always {
            node('built-in') {
                sh '''
                    echo "▶ Estado final da stack:"
                    /var/jenkins_home/docker stack ps keahubinnovation --no-trunc || true
                '''
            }
        }
    }
}
