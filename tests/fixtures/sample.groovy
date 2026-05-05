package pl.allegro.example

import pl.allegro.logistics.Processor
import pl.allegro.logistics.util.Helper

class SampleService {
    Processor processor

    SampleService(Processor processor) {
        this.processor = processor
    }

    String process(String input) {
        def result = processor.transform(input)
        return Helper.clean(result)
    }

    private void reset() {
        processor.reset()
    }
}
