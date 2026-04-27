<?php

return [
    'paths' => ['api/*', 'api/documentation*'],
    'allowed_methods' => ['*'],
    'allowed_origins' => [env('FRONTEND_URL', 'http://localhost:5173')],
    'allowed_origins_patterns' => ['^http://192\.168\..*:5173$', '^http://localhost:5173$'],
    'allowed_headers' => ['*'],
    'exposed_headers' => [],
    'max_age' => 0,
    'supports_credentials' => false,
];
