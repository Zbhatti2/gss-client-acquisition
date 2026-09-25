# Granite Signal Systems -- www.granitesignalsystems.com
# Static marketing/lead-capture site. Six plain HTML pages, no build step,
# no backend of its own -- the contact form (js/contact-form.js) POSTs
# straight to the GSS platform's public lead-intake API at app.ipromise.com
# (see js/config.js). Deployed the same way as the GSS app itself: Coolify,
# on the same VPS2 Ubuntu machine, git-push-to-deploy from this repo.
#
# No persistent volume needed here (unlike the GSS app's Dockerfile) --
# there is no database, no instance/ directory, nothing this container
# writes that needs to survive a redeploy. Every redeploy just serves
# whatever is currently in this repo.
FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY . /usr/share/nginx/html

EXPOSE 80
