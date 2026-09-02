# Stage 1: Build React SPA
FROM node:20-alpine AS build
WORKDIR /app

# Copy package files and install dependencies
COPY package*.json ./
RUN npm install

# Copy source code and build
COPY . ./
RUN npm run build

# Stage 2: Serve with Nginx
FROM nginx:alpine
# Copy the build output to replace the default nginx contents
COPY --from=build /app/dist /usr/share/nginx/html
# Copy the custom nginx configuration
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
