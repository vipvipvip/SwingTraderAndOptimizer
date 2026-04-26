<?php

use Illuminate\Support\Facades\Route;

Route::get('/', function () {
    return view('dashboard');
});

Route::get('/test', function () {
    return view('test');
});

Route::get('/api-docs', function () {
    return view('swagger');
});

Route::get('/api/documentation', function () {
    return file_get_contents(public_path('docs/swagger.html'));
});
