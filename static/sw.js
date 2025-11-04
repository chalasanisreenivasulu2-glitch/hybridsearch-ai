// Service Worker for HybridSearch AI PWA
// This enables offline functionality and caching

const CACHE_NAME = 'hybridsearch-v1';
const urlsToCache = [
  '/',
  '/static/sw.js',
  '/manifest.json'
];

// Install Event - Cache Resources
self.addEventListener('install', (event) => {
  console.log('[Service Worker] Installing...');
  
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => {
        console.log('[Service Worker] Caching app shell');
        return cache.addAll(urlsToCache);
      })
      .then(() => {
        console.log('[Service Worker] Install complete');
      })
      .catch((error) => {
        console.error('[Service Worker] Install failed:', error);
      })
  );
  
  // Force the waiting service worker to become the active service worker
  self.skipWaiting();
});

// Activate Event - Clean Up Old Caches
self.addEventListener('activate', (event) => {
  console.log('[Service Worker] Activating...');
  
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames.map((cacheName) => {
          if (cacheName !== CACHE_NAME) {
            console.log('[Service Worker] Deleting old cache:', cacheName);
            return caches.delete(cacheName);
          }
        })
      );
    })
  );
  
  // Take control of all pages immediately
  return self.clients.claim();
});

// Fetch Event - Serve from Cache, Fallback to Network
self.addEventListener('fetch', (event) => {
  event.respondWith(
    caches.match(event.request)
      .then((response) => {
        // Cache hit - return the cached response
        if (response) {
          console.log('[Service Worker] Serving from cache:', event.request.url);
          return response;
        }
        
        // Clone the request because it can only be used once
        const fetchRequest = event.request.clone();
        
        // Make network request
        return fetch(fetchRequest).then((response) => {
          // Check if we received a valid response
          if (!response || response.status !== 200 || response.type !== 'basic') {
            return response;
          }
          
          // Clone the response because it can only be used once
          const responseToCache = response.clone();
          
          // Cache static resources (CSS, JS, images)
          if (event.request.url.includes('/static/') || 
              event.request.url.match(/\.(css|js|png|jpg|jpeg|gif|svg|ico)$/)) {
            caches.open(CACHE_NAME)
              .then((cache) => {
                console.log('[Service Worker] Caching new resource:', event.request.url);
                cache.put(event.request, responseToCache);
              });
          }
          
          return response;
        }).catch((error) => {
          console.error('[Service Worker] Fetch failed:', error);
          
          // Return offline page if available
          return caches.match('/offline.html').then((offlineResponse) => {
            return offlineResponse || new Response('Offline - Please check your connection', {
              status: 503,
              statusText: 'Service Unavailable',
              headers: new Headers({
                'Content-Type': 'text/plain'
              })
            });
          });
        });
      })
  );
});

// Background Sync (Optional - for future enhancements)
self.addEventListener('sync', (event) => {
  console.log('[Service Worker] Background sync:', event.tag);
  
  if (event.tag === 'sync-searches') {
    event.waitUntil(
      // Sync logic here
      Promise.resolve()
    );
  }
});

// Push Notifications (Optional - for future enhancements)
self.addEventListener('push', (event) => {
  console.log('[Service Worker] Push received:', event);
  
  const options = {
    body: event.data ? event.data.text() : 'New notification',
    icon: '/static/icon-192.png',
    badge: '/static/badge-72.png',
    vibrate: [100, 50, 100],
    data: {
      dateOfArrival: Date.now(),
      primaryKey: 1
    }
  };
  
  event.waitUntil(
    self.registration.showNotification('HybridSearch AI', options)
  );
});

// Notification Click Handler
self.addEventListener('notificationclick', (event) => {
  console.log('[Service Worker] Notification clicked:', event);
  
  event.notification.close();
  
  event.waitUntil(
    clients.openWindow('/')
  );
});

// Message Handler (for communication with main app)
self.addEventListener('message', (event) => {
  console.log('[Service Worker] Message received:', event.data);
  
  if (event.data.action === 'skipWaiting') {
    self.skipWaiting();
  }
  
  if (event.data.action === 'clearCache') {
    event.waitUntil(
      caches.keys().then((cacheNames) => {
        return Promise.all(
          cacheNames.map((cacheName) => {
            return caches.delete(cacheName);
          })
        );
      }).then(() => {
        event.ports[0].postMessage({ success: true });
      })
    );
  }
});w