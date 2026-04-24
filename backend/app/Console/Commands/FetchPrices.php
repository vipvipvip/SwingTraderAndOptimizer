<?php

namespace App\Console\Commands;

use App\Services\PriceAcquisitionService;
use Illuminate\Console\Command;

class FetchPrices extends Command
{
    protected $signature = 'prices:fetch';
    protected $description = 'Fetch latest prices for all tickers and save to intra_day_prices table';

    private $priceAcquisitionService;

    public function __construct(PriceAcquisitionService $priceAcquisitionService)
    {
        parent::__construct();
        $this->priceAcquisitionService = $priceAcquisitionService;
    }

    public function handle()
    {
        try {
            $prices = $this->priceAcquisitionService->fetchLatestPrices();
            $count = count($prices);
            $this->info("Fetched prices for {$count} tickers");
            return 0;
        } catch (\Exception $e) {
            $this->error("Failed to fetch prices: " . $e->getMessage());
            return 1;
        }
    }
}
