<?php

namespace App\Logging;

use Monolog\Processor\IntrospectionProcessor;

class AddCallerProcessor
{
    public function __invoke($logger): void
    {
        $processor = new IntrospectionProcessor(
            skipClassesPartials: ['Monolog\\', 'Illuminate\\Log\\', 'Illuminate\\Support\\Facades\\']
        );

        foreach ($logger->getLogger()->getHandlers() as $handler) {
            $handler->pushProcessor($processor);
        }
    }
}
