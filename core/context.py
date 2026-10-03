from .services import predictor


def app_context(request):
    return {
        "APP_NAME": "EarlySignal NG",
        "model_ready": predictor.model_ready(),
    }
