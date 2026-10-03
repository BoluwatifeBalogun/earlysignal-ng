from django.core.management.base import BaseCommand, CommandError

from ml import pipeline


class Command(BaseCommand):
    help = "Train Random Forest and the Logistic Regression baseline, then deploy the better one."

    def add_arguments(self, parser):
        parser.add_argument("--data", help="Path to a labelled CSV. Defaults to the bundled dataset.")
        parser.add_argument("--permutations", type=int, default=100)

    def handle(self, *args, **opts):
        self.stdout.write("Training. This takes about half a minute...")
        try:
            m = pipeline.train(opts["data"], permutations=opts["permutations"])
        except pipeline.DatasetError as exc:
            raise CommandError(str(exc))
        d = m["data"]
        self.stdout.write(
            f"Records: {d['rows_raw']:,} raw, {d['duplicates_removed']} duplicates and "
            f"{d['missing_removed']} incomplete removed, {d['rows_used']:,} used "
            f"({d['train_rows']:,} train / {d['test_rows']:,} test)")
        for name, res in m["models"].items():
            t = res["test"]
            self.stdout.write(
                f"  {name:<20} accuracy {t['accuracy']:.3f}  precision {t['precision']:.3f}  "
                f"recall {t['recall']:.3f}  F1 {t['f1']:.3f}  (5-fold F1 {res['cv']['f1']['mean']:.3f})")
        self.stdout.write(self.style.SUCCESS(f"Deployed: {m['selected']}. {m['selection_reason']}"))
