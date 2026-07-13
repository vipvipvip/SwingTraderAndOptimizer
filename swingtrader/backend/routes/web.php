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

Route::get('/scanner', [\Scanner\Backend\Controllers\ScannerController::class, 'index']);
Route::get('/scanner/copy-tickers', [\Scanner\Backend\Controllers\ScannerController::class, 'copyTickers']);
Route::get('/scanner/data/{ticker}', [\Scanner\Backend\Controllers\ScannerController::class, 'chart']);
Route::get('/scanner/explorer', [\Scanner\Backend\Controllers\ScannerController::class, 'explorer']);
Route::get('/scanner/explorer-data', [\Scanner\Backend\Controllers\ScannerController::class, 'explorerData']);
Route::post('/scanner/update-valuations', [\Scanner\Backend\Controllers\ScannerController::class, 'updateValuations']);
