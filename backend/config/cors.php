<?php

return [
    'paths' => ['api/*', 'api/documentation*'],
    'allowed_methods' => ['*'],
    'allowed_origins' => [env('FRONTEND_URL', 'http://localhost:5173')],
'allowed_origins_patterns' => [
    '^http://192\.168\.1\..*:.*$',  // Any IP/port on your local network
    '^http://localhost:.*$',         // Localhost any port
],
    'allowed_headers' => ['*'],
    'exposed_headers' => [],
    'max_age' => 0,
    'supports_credentials' => false,
];
