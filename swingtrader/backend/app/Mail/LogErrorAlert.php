<?php

namespace App\Mail;

use Illuminate\Bus\Queueable;
use Illuminate\Mail\Mailable;
use Illuminate\Mail\Mailables\Content;
use Illuminate\Mail\Mailables\Envelope;
use Illuminate\Queue\SerializesModels;

class LogErrorAlert extends Mailable
{
    use Queueable, SerializesModels;

    public $errors;
    public $recipient;
    public $timestamp;

    public function __construct($errors, $recipient)
    {
        $this->errors = $errors;
        $this->recipient = $recipient;
        $this->timestamp = now();
    }

    public function envelope(): Envelope
    {
        return new Envelope(
            subject: '[SwingTrader Alert] ' . count($this->errors) . ' Error(s) in Logs',
            to: [$this->recipient]
        );
    }

    public function content(): Content
    {
        $errorList = implode("\n", array_map(fn($err) => "• " . $err, $this->errors));

        return new Content(
            text: "emails.log-error-alert",
            with: [
                'errors' => $this->errors,
                'errorList' => $errorList,
                'timestamp' => $this->timestamp,
                'count' => count($this->errors),
            ],
        );
    }
}
