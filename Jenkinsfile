pipeline {
    agent any

    environment {
        ENGINE_IMAGE    = "ghcr.io/fredd80/sbm-engine"
        API_IMAGE       = "ghcr.io/fredd80/sbm-api"
        WORKER_IMAGE    = "ghcr.io/fredd80/sbm-engine"   // same image as engine, different CMD
        DASHBOARD_IMAGE = "ghcr.io/fredd80/sbm-dashboard"
        IMAGE_TAG      = "${env.GIT_COMMIT[0..7]}"
        KUBECONFIG     = credentials('kubeconfig-multiverse')
    }

    stages {
        stage('Checkout') {
            steps {
                checkout scm
            }
        }

        stage('Test') {
            steps {
                sh '''
                    pip install -r requirements.txt -r requirements.api.txt
                    pytest tests/ -v --tb=short
                '''
            }
        }

        stage('Build Engine') {
            steps {
                sh "docker build -t ${ENGINE_IMAGE}:${IMAGE_TAG} ."
            }
        }

        stage('Build API') {
            steps {
                sh "docker build -f Dockerfile.api -t ${API_IMAGE}:${IMAGE_TAG} ."
            }
        }

        stage('Build Dashboard') {
            steps {
                sh "docker build -f Dockerfile.dashboard -t ${DASHBOARD_IMAGE}:${IMAGE_TAG} ."
            }
        }

        stage('Push') {
            steps {
                withCredentials([usernamePassword(credentialsId: 'registry-creds',
                                                  usernameVariable: 'REG_USER',
                                                  passwordVariable: 'REG_PASS')]) {
                    sh '''
                        echo "$REG_PASS" | docker login ghcr.io -u "$REG_USER" --password-stdin

                        docker push ${ENGINE_IMAGE}:${IMAGE_TAG}
                        docker push ${API_IMAGE}:${IMAGE_TAG}
                        docker push ${DASHBOARD_IMAGE}:${IMAGE_TAG}
                    '''
                }
            }
        }

        stage('Deploy') {
            steps {
                sh '''
                    # Prediction engine
                    kubectl --kubeconfig=$KUBECONFIG -n tenant-d set image \
                        deployment/sbm-engine \
                        engine=${ENGINE_IMAGE}:${IMAGE_TAG}
                    kubectl --kubeconfig=$KUBECONFIG -n tenant-d rollout status \
                        deployment/sbm-engine

                    # Celery worker (same image, different CMD in deployment.yaml)
                    kubectl --kubeconfig=$KUBECONFIG -n tenant-d set image \
                        deployment/sbm-worker \
                        worker=${ENGINE_IMAGE}:${IMAGE_TAG}
                    kubectl --kubeconfig=$KUBECONFIG -n tenant-d rollout status \
                        deployment/sbm-worker

                    # FastAPI
                    kubectl --kubeconfig=$KUBECONFIG -n tenant-d set image \
                        deployment/sbm-api \
                        api=${API_IMAGE}:${IMAGE_TAG}
                    kubectl --kubeconfig=$KUBECONFIG -n tenant-d rollout status \
                        deployment/sbm-api

                    # Dashboard
                    kubectl --kubeconfig=$KUBECONFIG -n tenant-d set image \
                        deployment/sbm-dashboard \
                        dashboard=${DASHBOARD_IMAGE}:${IMAGE_TAG}
                    kubectl --kubeconfig=$KUBECONFIG -n tenant-d rollout status \
                        deployment/sbm-dashboard

                    # Apply any new K8s manifests with IMAGE_TAG substituted in.
                    # Keeps manifests SHA-pinned even after a pod restart.
                    export IMAGE_TAG=${IMAGE_TAG}
                    find k8s -name "*.yaml" -print0 \
                      | xargs -0 -I {} sh -c 'envsubst < "$1" | kubectl --kubeconfig=$KUBECONFIG apply -f -' _ {}
                '''
            }
        }
    }

    post {
        failure {
            echo "Build failed — check test output above."
        }
    }
}
