FROM gitpod/workspace-full

# install and activate python 3.9
RUN pyenv update && pyenv install 3.9.6 && pyenv global 3.9.6