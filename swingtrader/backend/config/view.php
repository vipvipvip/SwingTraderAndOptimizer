<?php

return [
    'paths' => [
        resource_path('views'),
        base_path('../scanner/backend/views'),
    ],
    'compiled' => env(
        'VIEW_COMPILED_PATH',
        realpath(storage_path('framework/views'))
    ),
];
