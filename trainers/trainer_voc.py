from base.base_trainer import BaseTrainer
import tensorflow as tf
from evaluator.voceval import EvaluatorVOC
from tensorflow.python.keras import metrics
from yolo.yolo_loss import loss_yolo


class Trainer(BaseTrainer):
  def __init__(self, args, config, model, optimizer):
    super().__init__(args, config, model, optimizer)
    self.logger_scalas = {}
    self.logger_coco = ['mAP', 'mAp@50', 'mAP@75', 'mAP@small', 'mAP@meduim', 'mAP@large',
                        'AR@1', 'AR@10', 'AR@100', 'AR@small', 'AR@medium', 'AR@large']
    self.logger_pic = []

  def _get_loggers(self):
    self.TESTevaluator = EvaluatorVOC(anchors=self.anchors,
                                       inputsize=(self.configs['model']['net_size'],
                                                  self.configs['model']['net_size']),
                                       idx2cate=self.configs['model']['idx2cat'],
                                       threshold=self.configs['cls_threshold'],
                                       cateNames=self.configs['dataset']['labels'],
                                       num_images=self.num_test
                                      )

    self.LossBox = metrics.Mean()
    self.LossConf = metrics.Mean()
    self.LossClass = metrics.Mean()
    self.logger_scalas.update({"lossBox": self.LossBox})
    self.logger_scalas.update({"lossConf": self.LossConf})
    self.logger_scalas.update({"lossClass": self.LossClass})

  def _reset_loggers(self):
    self.TESTevaluator.reset()
    self.LossClass.reset_states()
    self.LossConf.reset_states()
    self.LossBox.reset_states()

  # @tf.function
  def train_step(self, imgs, labels):
    with tf.GradientTape() as tape:
      outputs = self.model(imgs, training=True)
      loss_box, loss_conf, loss_class = loss_yolo(outputs, labels, anchors=self.anchors,
                                                  inputshape=(self.net_size, self.net_size),
                                                  num_classes=self.num_classes)
      loss = tf.reduce_sum(loss_box + loss_conf + loss_class)
    grads = tape.gradient(loss, self.model.trainable_variables)
    self.optimizer.apply_gradients(zip(grads, self.model.trainable_variables))
    self.LossBox.update_state(loss_box)
    self.LossConf.update_state(loss_conf)
    self.LossClass.update_state(loss_class)
    return outputs

  def _valid_epoch(self):
    print("validation start")
    for idx_batch, (imgs, imgpath,annpath, scale, ori_shapes, *labels) in enumerate(self.test_dataloader):
      if idx_batch == self.args.valid_batch and not self.args.do_test:  # to save time
        break
      grids = self.model(imgs, training=False)
      print(grids[0][0,:6,:6,0])
      assert 0
      self.TESTevaluator.append(grids, imgpath,annpath, scale, ori_shapes, visualize=True)
    imgs = self.TESTevaluator.visual_imgs
    return imgs

  def _train_epoch(self):
    with self.trainwriter.as_default():
      for i, (img, imgpath,annpath,scale, ori_shapes, *labels) in enumerate(self.train_dataloader):
        self.global_iter.assign_add(1)
        if self.global_iter.numpy() % 100 == 0:
          print(self.global_iter.numpy())
          for k, v in self.logger_scalas.items():
            print(k, ":", v.result().numpy())

        _ = self.train_step(img, labels)
        if self.global_iter.numpy() % self.log_iter == 0:
          for k, v in self.logger_scalas.items():
            tf.summary.scalar(k, v.result(), step=self.global_iter.numpy())
          imgs = self._valid_epoch()
          for i in range(len(imgs)):
            tf.summary.image("detections_{}".format(i), tf.expand_dims(tf.convert_to_tensor(imgs[i]), 0),
                             step=self.global_iter.numpy())
          self._reset_loggers()
    self.ckpt_manager.save(self.global_epoch)
