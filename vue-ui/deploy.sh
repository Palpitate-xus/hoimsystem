#强制推送
#!/usr/bin/env bash
set -e
npm run build
cd dist
touch .nojekyll
git init
git add -A
git commit -m 'deploy'
# git push -f "https://${access_token}@gitee.com" master:gh-pages
# start "https://gitee.com/"
# git push -f "https://${access_token}@github.com" master:gh-pages
cd -
exec /bin/bash




