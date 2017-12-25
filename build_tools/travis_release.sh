
current_branch="$TRAVIS_BRANCH"

if [ "master" = $current_branch ]; then
    echo "master"
    YAPTIDE_BASE_URL="http://149.156.11.4:10206" ./build_tools/release.sh
elif [ "develop" = $current_branch ]; then
    echo "develop"
    YAPTIDE_BASE_URL="http://149.156.11.4:10207" ./build_tools/release.sh
else
    echo "staging"
    YAPTIDE_BASE_URL="http://149.156.11.4:10208" ./build_tools/release.sh
fi


