# nginx/certs 目录说明
#
# 本目录放 TLS 证书和私钥。
# !! 这两个文件必须在 .gitignore 里屏蔽，绝不能提交到 git。
#
# 准备（生产环境）：
#   # Let\'s Encrypt（免费，自动续期）—— 推荐
#   certbot certonly --standalone -d faq.niit.edu.cn
#   cp /etc/letsencrypt/live/faq.niit.edu.cn/fullchain.pem nginx/certs/
#   cp /etc/letsencrypt/live/faq.niit.edu.cn/privkey.pem   nginx/certs/
#
# 准备（本地测试）—— 用 mkcert 自签：
#   choco install mkcert       # Windows
#   mkcert -install
#   mkcert faq.local           # 生成 faq.local.pem + faq.local-key.pem
#   # 重命名为：
#   mv faq.local.pem        nginx/certs/fullchain.pem
#   mv faq.local-key.pem    nginx/certs/privkey.pem
#
# 准备（纯开发环境，跳过 TLS）—— 改 nginx.conf 注释掉 443 段，临时用 HTTP：
#   # 注释掉 server { listen 443 ... } 整块
#   # 同时把 server { listen 80 } 的 return 301 注释掉
#
# !! 本地测试时浏览器会拒绝访问自签证书，需要手动信任。