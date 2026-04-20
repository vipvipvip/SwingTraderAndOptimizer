<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use App\Services\AlpacaService;
use Illuminate\Http\Request;

class OrderController extends Controller
{
    private $alpacaService;

    public function __construct(AlpacaService $alpacaService)
    {
        $this->alpacaService = $alpacaService;
    }

    public function place(Request $request)
    {
        $validated = $request->validate([
            'symbol' => 'required|string',
            'side' => 'required|in:buy,sell',
            'qty' => 'required|integer|min:1',
        ]);

        try {
            $order = $this->alpacaService->placeOrder(
                $validated['symbol'],
                $validated['side'],
                $validated['qty']
            );
            return response()->json($order, 201);
        } catch (\Exception $e) {
            return response()->json(['error' => $e->getMessage()], 500);
        }
    }

    public function cancel($orderId)
    {
        try {
            $this->alpacaService->cancelOrder($orderId);
            return response()->json(['message' => 'Order cancelled']);
        } catch (\Exception $e) {
            return response()->json(['error' => $e->getMessage()], 500);
        }
    }
}
