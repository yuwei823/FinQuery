FROM node:20.19-alpine AS development

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]

FROM development AS build

RUN npm run build

FROM nginx:1.27-alpine AS production

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

FROM production AS public-preview

COPY nginx.public.conf /etc/nginx/conf.d/default.conf
COPY proxy-common.conf /etc/nginx/snippets/proxy-common.conf
