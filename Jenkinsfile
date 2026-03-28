pipeline {
    agent any

    environment {
        IMAGE_NAME = "your-registry/soccer-betting-model"
        IMAGE_TAG  = "${env.GIT_COMMIT[0..7]}"
        KUBECONFIG = credentials('kubeconfig-multiverse')
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
                    pip install -r requirements.txt
                    pytest tests/ -v --tb=short
                '''
            }
        }

        stage('Build') {
            steps {
                sh "docker build -t ${IMAGE_NAME}:${IMAGE_TAG} ."
            }
        }

        stage('Push') {
            steps {
                withCredentials([usernamePassword(credentialsId: 'registry-creds',
                                                  usernameVariable: 'REG_USER',
                                                  passwordVariable: 'REG_PASS')]) {
                    sh '''
                        echo "$REG_PASS" | docker login -u "$REG_USER" --password-stdin
                        docker push ${IMAGE_NAME}:${IMAGE_TAG}
                        docker tag ${IMAGE_NAME}:${IMAGE_TAG} ${IMAGE_NAME}:latest
                        docker push ${IMAGE_NAME}:latest
                    '''
                }
            }
        }

        stage('Deploy') {
            steps {
                sh '''
                    kubectl --kubeconfig=$KUBECONFIG -n tenant-b set image \
                        deployment/soccer-betting-model \
                        app=${IMAGE_NAME}:${IMAGE_TAG}
                    kubectl --kubeconfig=$KUBECONFIG -n tenant-b rollout status \
                        deployment/soccer-betting-model
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
